#!/usr/bin/env python3
"""Transactional gateway maintenance. Never executes imported profile hooks."""
import argparse
import base64
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

ENV = '/etc/awg-pbr/env'
DNS = '/etc/dnsmasq.d/99-awg-pbr.conf'
NFT = '/etc/nftables.d/99-awg-pbr.nft'
CLIENTS = '/etc/awg-pbr/clients.txt'
DOMAINS = '/etc/dnsmasq.d/99-awg-pbr-domains.conf'
HEALTH = 'awg-pbr-health.service'
TIMER = 'awg-opencck-update.timer'
UPDATER = 'awg-opencck-update.service'
BACKUPS = '/var/backups/awg-gateway'
FAILOPEN = '/usr/local/sbin/awg-pbr-failopen'
SETUP = '/usr/local/sbin/awg-pbr-setup'
ROUTE = '/usr/local/sbin/awg-route'
CONF_DIR = '/etc/amnezia/amneziawg'


def run(*args, check=True):
    # Command stderr may contain private configuration: never forward it.
    child_env = os.environ.copy()
    if args[0] == ROUTE:
        child_env['AWG_MAINTENANCE'] = '1'
    result = subprocess.run(args, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=90, env=child_env)
    if check and result.returncode:
        raise RuntimeError(f'Ошибка команды {Path(args[0]).name}; код {result.returncode}')
    return result


def read_env():
    env = {}
    for line in Path(ENV).read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, sep, value = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Z_][A-Z_0-9]*', key):
            raise ValueError('Некорректный env')
        parts = shlex.split(value, comments=True)
        if len(parts) != 1:
            raise ValueError('Некорректное значение env')
        env[key] = parts[0]
    return env


def atomic(path, content, mode=0o600):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix='.awg-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as out:
            out.write(content.encode() if isinstance(content, str) else content)
            out.flush()
            os.fsync(out.fileno())
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def discover(env):
    routes = json.loads(run('ip', '-j', '-4', 'route', 'show', 'table', 'main', 'default').stdout)
    candidates = [r for r in routes if r.get('gateway') and r.get('dev') != env['VPN_IF']]
    if not candidates:
        raise ValueError('Не найден IPv4 default route через LAN router')
    best_metric = min(r.get('metric', 0) for r in candidates)
    candidates = [r for r in candidates if r.get('metric', 0) == best_metric]
    if len(candidates) != 1:
        raise ValueError('Неоднозначные default routes; исправьте маршруты перед перенастройкой')
    route = candidates[0]
    dev = route['dev']
    if not re.fullmatch(r'[a-zA-Z0-9_.:-]{1,15}', dev):
        raise ValueError('Некорректный LAN interface')
    router = ipaddress.IPv4Address(route['gateway'])
    addresses = json.loads(run('ip', '-j', '-4', 'addr', 'show', 'dev', dev, 'scope', 'global').stdout)
    eligible = []
    for device in addresses:
        for addr in device.get('addr_info', []):
            iface = ipaddress.IPv4Interface(f"{addr['local']}/{addr['prefixlen']}")
            if router in iface.network:
                eligible.append(iface)
    if route.get('prefsrc'):
        eligible = [a for a in eligible if str(a.ip) == route['prefsrc']]
    if len(eligible) != 1:
        raise ValueError('Неоднозначный/отсутствующий IPv4 адрес в подсети router')
    iface = eligible[0]
    return dict(LAN_IF=dev, PI_IP=str(iface.ip), LAN_CIDR=str(iface.network), ROUTER_IP=str(router))


def network_status(env):
    try:
        actual = discover(env)
        if any(env.get(k) != v for k, v in actual.items()):
            print('WARNING: фактическая сеть отличается от сохранённой; awg-route network reconfigure')
            for k, v in actual.items():
                print(f'  {k}: saved={env.get(k)} actual={v}')
    except (ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'WARNING: сеть не проверена: {exc}')


def confirm(args, prompt):
    if args.yes:
        return
    try:
        with open('/dev/tty', 'r+') as tty:
            tty.write(prompt + ' [y/N]: ')
            tty.flush()
            answer = tty.readline().strip().lower()
    except OSError:
        raise ValueError('Нужен терминал для подтверждения; для автоматизации используйте --yes') from None
    if answer not in ('y', 'yes', 'д', 'да'):
        raise ValueError('Операция отменена; настройки не изменены')


class Transaction:
    def __init__(self, kind, files):
        Path(BACKUPS).mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(BACKUPS, 0o700)
        self.directory = Path(tempfile.mkdtemp(prefix=kind + '-' + time.strftime('%Y%m%d-%H%M%S-'), dir=BACKUPS))
        self.files = list(files)
        self.present = {}
        for i, name in enumerate(self.files):
            path = Path(name)
            self.present[name] = path.exists()
            if path.exists():
                shutil.copy2(path, self.directory / str(i))
                os.chmod(self.directory / str(i), 0o600)
        atomic(self.directory / 'manifest.json', json.dumps(self.files))
        self.health = run('systemctl', 'is-active', '--quiet', HEALTH, check=False).returncode == 0
        self.timer = run('systemctl', 'is-active', '--quiet', TIMER, check=False).returncode == 0
        print(f'Backup: {self.directory}')

    def pause(self):
        run('systemctl', 'stop', TIMER, UPDATER, HEALTH)
        run(FAILOPEN)

    def restore(self):
        for i, name in enumerate(self.files):
            if self.present[name]:
                atomic(name, (self.directory / str(i)).read_bytes())
            else:
                Path(name).unlink(missing_ok=True)

    def resume(self, healthy=True):
        if self.health and healthy:
            run('systemctl', 'start', HEALTH)
        if self.timer:
            run('systemctl', 'start', TIMER)


def reconfigure(args, env):
    actual = discover(env)
    for k, v in actual.items():
        print(f'{k}: {env.get(k)} -> {v}')
    if all(env.get(k) == v for k, v in actual.items()):
        print('Сеть не изменилась.')
        return
    outside = []
    for line in Path(CLIENTS).read_text().splitlines():
        value = line.split('#', 1)[0].strip()
        if value and ipaddress.IPv4Address(value) not in ipaddress.IPv4Network(actual['LAN_CIDR']):
            outside.append(value)
    if outside:
        print('WARNING: клиенты вне новой подсети: ' + ', '.join(outside))
        print('Allow-list сохраняется: старые адреса не будут соответствовать новым клиентам. '
              'Добавьте новые адреса через client add; не очищайте список (пустой = все клиенты).')
        if not args.keep_clients:
            if args.yes:
                raise ValueError('Для сохранения старого allow-list требуется --keep-clients')
            confirm(args, 'Сохранить старые адреса allow-list и исправить их вручную?')
    confirm(args, 'Применить обнаруженную сеть? DHCP reservation и gateway/DNS клиентов настройте на router')
    # Re-check after the prompt, avoiding applying a stale DHCP snapshot.
    if discover(env) != actual:
        raise ValueError('Сеть изменилась во время подтверждения; повторите команду')
    new_env = Path(ENV).read_text()
    for k, v in actual.items():
        new_env, count = re.subn(r'^' + k + r'=.*$', k + '=' + shlex.quote(v), new_env, flags=re.M)
        if count != 1:
            raise ValueError(f'Ожидалась одна запись {k} в env')
    dns = Path(DNS).read_text()
    dns, interfaces = re.subn(r'^interface=.*$', 'interface=' + actual['LAN_IF'], dns, flags=re.M)
    dns, listeners = re.subn(r'^listen-address=' + re.escape(env['PI_IP']) + r'$', 'listen-address=' + actual['PI_IP'], dns, flags=re.M)
    if interfaces != 1 or listeners != 1:
        raise ValueError('Неоднозначная dnsmasq конфигурация; ожидается один LAN interface/listen-address')
    tx = Transaction('network', [ENV, DNS, NFT, DOMAINS, CLIENTS])
    try:
        tx.pause()
        atomic(ENV, new_env)
        atomic(DNS, dns)
        run('dnsmasq', '--test')
        run(SETUP)
        # reload regenerates domain/static sets and restarts health, so keep it
        # gated until all network checks have completed.
        run('systemctl', 'restart', 'dnsmasq.service')
        run('ping', '-4', '-n', '-c1', '-W3', actual['ROUTER_IP'])
        answer = run('dig', '+time=3', '+tries=1', '+short', 'A', 'example.com', '@' + actual['PI_IP']).stdout
        if not any(re.fullmatch(r'\d+(\.\d+){3}', x) for x in answer.splitlines()):
            raise RuntimeError('DNS через новый адрес Pi не отвечает')
        run(ROUTE, 'reload')
        if not tx.health:
            run('systemctl', 'stop', HEALTH)
        tx.resume()
    except BaseException:
        print('Ошибка перенастройки; восстанавливаем сохранённую конфигурацию.', file=sys.stderr)
        run('systemctl', 'stop', HEALTH, check=False)
        run(FAILOPEN, check=False)
        tx.restore()
        try:
            run(ROUTE, 'reload')
            if not tx.health:
                run('systemctl', 'stop', HEALTH)
            tx.resume()
        except Exception:
            run('systemctl', 'stop', HEALTH, check=False)
            run(FAILOPEN, check=False)
            print('Rollback файлов выполнен; восстановление сервисов не удалось. Policy DIRECT.', file=sys.stderr)
        raise
    print('Сеть обновлена; allow-list, DNS upstream и списки маршрутизации сохранены.')


def profile(text):
    """Strict native gateway profile; reject executable hooks and unknown fields."""
    allowed = {'Interface': {'PrivateKey', 'Address', 'ListenPort', 'MTU', 'FwMark',
                             'Jc', 'Jmin', 'Jmax', 'S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4',
                             'I1', 'I2', 'I3', 'I4', 'I5', 'DNS', 'Table',
                             'HeaderProtectionKey', 'ContentPaddingAddition', 'RekeyAfterTime',
                             'RekeyTimeout', 'RejectAfterTime', 'KeepaliveTimeout',
                             'MaxHandshakeAttempts', 'RandomTrailers', 'DisableCookies'},
               'Peer': {'PublicKey', 'PresharedKey', 'Endpoint', 'AllowedIPs', 'PersistentKeepalive',
                        'AdvancedSecurity'}}
    sections = []
    current = None
    for raw in text.splitlines():
        line = raw.split('#', 1)[0].strip()
        if not line:
            continue
        if line in ('[Interface]', '[Peer]'):
            current = (line[1:-1], {})
            sections.append(current)
            continue
        key, sep, value = line.partition('=')
        key, value = key.strip(), value.strip()
        if current is None or not sep or key not in allowed[current[0]] or not value:
            raise ValueError('Недопустимое поле native .conf (hooks/SaveConfig запрещены)')
        if key in current[1]:
            raise ValueError('Повторяющееся поле в .conf')
        current[1][key] = value
    if [s[0] for s in sections] != ['Interface', 'Peer']:
        raise ValueError('Нужны ровно [Interface] и один [Peer] для gateway')
    interface, peer = sections[0][1], sections[1][1]
    # AWG v3 header protection profiles need not contain the legacy H1-H4.
    # Let the installed core validate AWG combinations and value ranges.
    for section, required in ((interface, ('PrivateKey', 'Address')),
                              (peer, ('PublicKey', 'Endpoint', 'AllowedIPs'))):
        if not all(k in section for k in required):
            raise ValueError('Отсутствуют обязательные native AmneziaWG поля')
    awg_fields = {'Jc', 'Jmin', 'Jmax', 'S1', 'S2', 'S3', 'S4', 'H1', 'H2', 'H3', 'H4',
                  'I1', 'I2', 'I3', 'I4', 'I5', 'HeaderProtectionKey'}
    if not awg_fields.intersection(interface):
        raise ValueError('В профиле отсутствуют параметры AmneziaWG')
    for section in (interface, peer):
        for key in ('PrivateKey', 'PublicKey', 'PresharedKey', 'HeaderProtectionKey'):
            if key in section:
                try:
                    if len(base64.b64decode(section[key], validate=True)) != 32:
                        raise ValueError()
                except ValueError:
                    raise ValueError('Некорректный ключ в .conf') from None
    addresses = [ipaddress.ip_interface(v.strip()) for v in interface['Address'].split(',')]
    if not any(a.version == 4 for a in addresses):
        raise ValueError('Gateway требует IPv4 Address')
    # Preserve IPv6 entries from native exports. Table=off means they do not
    # enable IPv6 routing; this gateway still manages IPv4 policy only.
    networks = [ipaddress.ip_network(v.strip(), strict=False) for v in peer['AllowedIPs'].split(',')]
    if ipaddress.IPv4Network('0.0.0.0/0') not in networks:
        raise ValueError('Gateway требует AllowedIPs = 0.0.0.0/0')
    if not re.fullmatch(r'[A-Za-z0-9.-]+:[0-9]{1,5}', peer['Endpoint']):
        raise ValueError('Ожидается IPv4/hostname:port Endpoint')
    if not 1 <= int(peer['Endpoint'].rsplit(':', 1)[1]) <= 65535:
        raise ValueError('Некорректный порт Endpoint')
    for key in ('Jc', 'Jmin', 'Jmax', 'S1', 'S2', 'S3', 'S4', 'ListenPort', 'MTU'):
        if key in interface and not re.fullmatch(r'\d{1,10}', interface[key]):
            raise ValueError('Некорректный числовой AWG параметр')
    interface.pop('DNS', None)
    interface['Table'] = 'off'
    clean = ''.join('[' + name + ']\n' + ''.join(f'{k} = {v}\n' for k, v in fields.items()) + '\n'
                    for name, fields in sections)
    return clean, peer['Endpoint']


def preflight(path, env):
    # strip validates awg-quick parsing without executing the profile. Core
    # parsing is checked on a disposable interface in a private network namespace.
    stripped = run('awg-quick', 'strip', str(path)).stdout
    core = path.parent / 'core.conf'
    # Endpoint DNS resolution is validated separately on the live namespace.
    # No need to resolve/contact it from an isolated network namespace.
    endpoint = re.search(r'^Endpoint\s*=\s*(.*)$', stripped, re.M)
    if not endpoint:
        raise ValueError('awg-quick strip не вернул Endpoint')
    host = endpoint[1].strip().rsplit(':', 1)[0]
    import socket
    socket.getaddrinfo(host, None, socket.AF_INET, socket.SOCK_DGRAM)
    atomic(core, re.sub(r'^Endpoint\s*=.*$', '', stripped, flags=re.M))
    name = 'ac' + str(os.getpid())
    script = '''set -eu
trap 'ip link del "$1" 2>/dev/null || true; rm -f "/var/run/amneziawg/$1.sock"' EXIT
amneziawg-go "$1" >/dev/null 2>&1
awg setconf "$1" "$2" >/dev/null 2>&1
'''
    run('unshare', '--net', '--', 'bash', '-c', script, 'awg-preflight', name, str(core))


def tunnel_ok(env, since):
    mark = str(int(env['HEALTH_MARK'], 0))
    run('ip', '-4', 'route', 'replace', 'default', 'dev', env['VPN_IF'], 'table', env['HEALTH_TABLE'])
    # A unique probe rule avoids changing existing health rules during validation.
    rule = ('priority', '89', 'fwmark', mark, 'lookup', env['HEALTH_TABLE'])
    run('ip', '-4', 'rule', 'add', *rule)
    try:
        for _ in range(10):
            transport = any(run('ping', '-4', '-n', '-I', env['VPN_IF'], '-m', mark,
                                '-c1', '-W2', target, check=False).returncode == 0
                            for target in ('1.1.1.1', '9.9.9.9'))
            output = run('awg', 'show', env['VPN_IF'], 'latest-handshakes').stdout
            stamps = [int(line.split()[1]) for line in output.splitlines() if len(line.split()) == 2]
            now = int(time.time())
            if transport and stamps and all(s >= since and 0 <= now - s <= 180 for s in stamps):
                return True
            time.sleep(2)
        return False
    finally:
        run('ip', '-4', 'rule', 'del', *rule, check=False)


def replace_config(args, env):
    vpn = env['VPN_IF']
    if not re.fullmatch(r'[a-zA-Z0-9_=+.-]{1,15}', vpn):
        raise ValueError('Некорректный VPN_IF')
    active = Path(CONF_DIR) / (vpn + '.conf')
    previous = active.with_suffix('.conf.previous')
    source = previous if args.action == 'rollback' else Path(args.file)
    clean, endpoint = profile(source.read_text())
    old_endpoint = re.search(r'^\s*Endpoint\s*=\s*([^#\r\n]+)', active.read_text(), re.M)
    print('Старый Endpoint: ' + (old_endpoint[1].strip() if old_endpoint else '(не указан)'))
    print('Новый Endpoint: ' + endpoint)
    with tempfile.TemporaryDirectory(prefix='awg-preflight-') as temp:
        candidate = Path(temp) / (vpn + '.conf')
        atomic(candidate, clean)
        preflight(candidate, env)
        if args.action == 'check':
            print('Native профиль и AWG core validation: OK. Рабочая конфигурация и сервисы не изменены.')
            return
        confirm(args, 'Заменить профиль? На время проверки трафик будет DIRECT')
        tx = Transaction('config', [str(active), str(previous)])
        old = active.read_bytes()
        service = f'awg-quick@{vpn}.service'
        try:
            tx.pause()
            # Down reads the old profile, never the replacement.
            run('systemctl', 'stop', service)
            atomic(active, clean)
            since = int(time.time())
            run('systemctl', 'start', service)
            if not tunnel_ok(env, since):
                raise RuntimeError('Новый профиль: handshake/transport не прошли проверку')
            atomic(previous, old)
            tx.resume()
        except BaseException:
            print('Ошибка профиля; автоматический rollback.', file=sys.stderr)
            run('systemctl', 'stop', HEALTH, check=False)
            run(FAILOPEN, check=False)
            run('systemctl', 'stop', service, check=False)
            tx.restore()
            recovered = False
            try:
                since = int(time.time())
                run('systemctl', 'start', service)
                recovered = tunnel_ok(env, since)
                tx.resume(healthy=recovered)
            finally:
                if not recovered:
                    run('systemctl', 'stop', HEALTH, check=False)
                    run(FAILOPEN, check=False)
                    print('Старый файл возвращён, туннель не подтверждён: DIRECT; health остановлен.', file=sys.stderr)
            raise
    print('Профиль активирован. Handshake: OK. Transport: OK. Остальные настройки сохранены.')


def main():
    parser = argparse.ArgumentParser(description='AWG gateway maintenance')
    sub = parser.add_subparsers(dest='command', required=True)
    network = sub.add_parser('network')
    network.add_argument('action', choices=['status', 'reconfigure'])
    network.add_argument('--yes', action='store_true')
    network.add_argument('--keep-clients', action='store_true')
    config = sub.add_parser('config')
    config.add_argument('action', choices=['check', 'replace', 'rollback'])
    config.add_argument('file', nargs='?')
    config.add_argument('--yes', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('Требуются права root')
    if args.command == 'config' and ((args.action in ('replace', 'check')) != bool(args.file)):
        parser.error('config check FILE | config replace FILE | config rollback')
    env = read_env()
    if args.command == 'network' and args.action == 'status':
        network_status(env)
        return
    import fcntl
    with open('/run/awg-maintenance.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        def interrupted(signum, _frame):
            raise RuntimeError(f'Операция прервана сигналом {signum}')
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, interrupted)
        if args.command == 'network':
            reconfigure(args, env)
        else:
            replace_config(args, env)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not expose config values via parsing exceptions (keys/hooks etc.).
        if isinstance(error, (ValueError, RuntimeError)):
            print(str(error), file=sys.stderr)
        else:
            print(f'Операция не выполнена ({type(error).__name__}); проверьте доступность файлов и команд.', file=sys.stderr)
        sys.exit(1)
