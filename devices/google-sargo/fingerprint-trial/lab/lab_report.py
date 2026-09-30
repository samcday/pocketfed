"""Small checksummed UART records for fingerprint lab metadata only."""
import base64
import hashlib
import json
from pathlib import Path
import re
import zlib


def emit(name, value):
    assert re.fullmatch(r'[a-z_]+', name)
    raw = json.dumps(value, separators=(',', ':')).encode()
    digest = hashlib.sha256(raw).hexdigest()
    data = base64.b64encode(zlib.compress(raw)).decode()
    chunks = [data[i:i + 192] for i in range(0, len(data), 192)]
    root = Path('/run/pocketfed-fingerprint-lab')
    root.mkdir(mode=0o700, exist_ok=True)
    (root / (name + '.json')).write_bytes(raw)
    for index, chunk in enumerate(chunks):
        # Duplicate metadata records tolerate one console collision. These are
        # not retries of device operations. Full SHA256 is checked by collector.
        line = f'SARGO_LAB {name} {digest} {index}/{len(chunks)} {chunk}'
        print(line, flush=True)
        print(line, flush=True)


def collect(raw):
    groups = {}
    pattern = rb'SARGO_LAB ([a-z_]+) ([a-f0-9]{64}) ([0-9]+)/([0-9]+) ([A-Za-z0-9+/=]+)'
    for name, digest, index, count, chunk in re.findall(pattern, raw):
        index, count = int(index), int(count)
        if not 0 <= index < count <= 256:
            continue
        key = (name.decode(), digest.decode(), count)
        parts = groups.setdefault(key, {})
        parts.setdefault(index, set()).add(chunk)
    results = {}
    for (name, digest, count), parts in groups.items():
        if set(parts) != set(range(count)):
            continue
        # Prefer a full-length copy when a kernel line interrupted its duplicate.
        chunks = [max(parts[i], key=len) for i in range(count)]
        try:
            value = zlib.decompress(base64.b64decode(b''.join(chunks), validate=True))
            if len(value) > 256 * 1024 or hashlib.sha256(value).hexdigest() != digest:
                continue
            obj = json.loads(value)
        except (ValueError, zlib.error):
            continue
        if name in results and results[name] != obj:
            raise ValueError('conflicting verified reports: ' + name)
        results[name] = obj
    return results
