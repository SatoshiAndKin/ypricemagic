import json
from pathlib import Path
import platform
import time
import urllib.error
import urllib.request

base = Path('/private/tmp/yprice-memory')
values = dict(line.split('=', 1) for line in (base/'runtime.env').read_text().splitlines() if '=' in line)
url = values['VALIDATION_RPC_URL']
tx = {'to': '0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48', 'data': '0x313ce567'}
block = {'blockHash': '0x6e65cf41a9208837f764d22dd0358f7d67f57cd71ec5ee975d98674e292322bd', 'requireCanonical': True}
rows = []
for label, target in (('latest', 'latest'), ('hash-16830000', block)):
    started = time.monotonic()
    row = dict(label=label, method='eth_call', params=[tx, target], timeout_seconds=90)
    try:
        body = json.dumps(dict(jsonrpc='2.0', id=1, method='eth_call', params=[tx, target])).encode()
        request = urllib.request.Request(url, body, {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=90) as response:
            payload = json.load(response)
        row['result'] = payload.get('result')
        if 'error' in payload:
            row['rpc_error'] = payload['error']
    except Exception as error:
        row['error_type'] = type(error).__name__
        if isinstance(error, urllib.error.HTTPError):
            row['http_status'] = error.code
    row['elapsed_seconds'] = time.monotonic()-started
    rows.append(row)
    print(json.dumps(row), flush=True)
(base/'archive-recovery-host.json').write_text(json.dumps(dict(complete=True, origin=platform.system(), scope='Bounded standard-library HTTP diagnostics only; no project imports or host test execution', calls=rows), indent=2)+'\n')
