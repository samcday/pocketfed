#!/usr/bin/python3
import base64
import hashlib
import json
import unittest
import zlib
from lab_report import collect


class ReportTest(unittest.TestCase):
    def test_capture_integrity(self):
        value = {'firmware': list(range(300)), 'secure_calls': False}
        raw = json.dumps(value, separators=(',', ':')).encode()
        digest = hashlib.sha256(raw).hexdigest()
        encoded = base64.b64encode(zlib.compress(raw)).decode()
        parts = [encoded[i:i+192] for i in range(0, len(encoded), 192)]
        lines = [f'[ 50.0] python3[1]: SARGO_LAB inspection {digest} {i}/{len(parts)} {x}\n'.encode()
                 for i,x in enumerate(parts)]
        self.assertEqual(collect(b''.join(lines)), {'inspection': value})
        noisy = b''.join(line[:150] + b'[ 50.1] audit: unrelated\n' + line for line in lines)
        self.assertEqual(collect(noisy), {'inspection': value})
        self.assertEqual(collect(b''.join(lines[:-1])), {})
        self.assertEqual(collect(b''.join(lines).replace(digest.encode(), b'0'*64)), {})
        self.assertEqual(collect(b''.join(lines).replace(parts[-1].encode(), b'BAD=')), {})


if __name__ == '__main__':
    unittest.main()
