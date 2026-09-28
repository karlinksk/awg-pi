"""Real isolated preflight with the same pinned AWG versions as the test Pi."""
import base64
from pathlib import Path
import runpy
import re
import subprocess
import tempfile

ns = runpy.run_path('tests/test-maintenance.py')
m = ns['m']
private = m.run('awg', 'genkey').stdout.strip()
peer_private = m.run('awg', 'genkey').stdout.strip()
public = subprocess.run(['awg', 'pubkey'], input=peer_private, text=True,
                        capture_output=True, check=True).stdout.strip()

# Synthetic profiles only: expose sanitized command errors in CI so failures
# remain actionable. Production preflight keeps command stderr private.
original_run = m.run
def test_run(*args, **kwargs):
    if args[0] != 'unshare':
        return original_run(*args, **kwargs)
    args = list(args)
    args[5] = args[5].replace('>/dev/null 2>&1', '')
    result = subprocess.run(args, text=True, capture_output=True, timeout=90)
    if result.returncode:
        message = re.sub(r'[A-Za-z0-9+/]{43}=', '(synthetic key hidden)', result.stderr)
        print(message)
        raise RuntimeError('Isolated synthetic profile rejected')
    return result
m.run = test_run

with tempfile.TemporaryDirectory() as temp:
    candidate = Path(temp) / 'awgcheck.conf'
    for name in ('PROFILE', 'V3_PROFILE'):
        text = ns[name].replace('PrivateKey = ' + ns['KEY'], 'PrivateKey = ' + private)
        text = text.replace('PublicKey = ' + ns['KEY'], 'PublicKey = ' + public)
        text = text.replace('HeaderProtectionKey = ' + ns['KEY'],
                            'HeaderProtectionKey = ' + base64.b64encode(bytes(range(32))).decode())
        clean, _ = m.profile(text)
        m.atomic(candidate, clean)
        m.preflight(candidate, {'VPN_IF': 'awgcheck'})
        print(name + ': actual AWG v3.1 preflight passed')
    # Values the gateway leaves to the installed core must still fail safely.
    m.atomic(candidate, clean.replace('RandomTrailers = on', 'RandomTrailers = invalid'))
    try:
        m.preflight(candidate, {'VPN_IF': 'awgcheck'})
    except RuntimeError:
        print('Invalid core parameter rejected before live changes')
    else:
        raise AssertionError('Core accepted invalid RandomTrailers')
