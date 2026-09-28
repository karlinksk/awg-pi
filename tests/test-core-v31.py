"""Real isolated preflight with the same pinned AWG versions as the test Pi."""
import base64
from pathlib import Path
import runpy
import subprocess
import tempfile

ns = runpy.run_path('tests/test-maintenance.py')
m = ns['m']
private = m.run('awg', 'genkey').stdout.strip()
public = subprocess.run(['awg', 'pubkey'], input=private, text=True,
                        capture_output=True, check=True).stdout.strip()

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
