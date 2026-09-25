#!/usr/bin/env python3
"""Regression tests for msm dump block boundaries and incomplete packets."""

import base64
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('devcore-cp-scan.py')
SPEC = importlib.util.spec_from_file_location('devcore_cp_scan', SCRIPT)
SCAN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCAN)


def encode(words):
    return base64.a85encode(b''.join(w.to_bytes(4, 'big') for w in words)).decode()


def constant_load(block):
    return [0xc0013000, (32 << 22) | (block << 19) | (4 << 16) | 16,
            0x12345241]


class PayloadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'dump'

    def write(self, text):
        self.path.write_text(text)
        return self.path

    def test_yaml_keys_are_not_payload(self):
        # Both following section names are in the ascii85 alphabet. The old
        # parser appended them, corrupting data or reporting Ascii85 overflow.
        ring = constant_load(4)
        bo = constant_load(6)
        self.write(f'''ringbuffer:
  - iova: 0x1000
    size: 12
    data: !!ascii85 |
     {encode(ring)}
bos:
  - iova: 0x2000
    size: 12
    data: !!ascii85 |
     {encode(bo)}
registers:
  - {{ offset: 0x0000, value: 0x00060000 }}
''')
        payloads = list(SCAN.payloads(self.path))
        self.assertEqual([label for label, _ in payloads],
                         ['0x1000 size=12', '0x2000 size=12'])
        self.assertEqual([SCAN.dwords(chunks) for _, chunks in payloads],
                         [ring, bo])
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(SCAN.main(['devcore-cp-scan.py', str(self.path)]), 0)
        self.assertNotIn('undecodable', output.getvalue())
        self.assertIn('CP_LOAD_STATE packets:            2', output.getvalue())
        self.assertIn('SS_INDIRECT SB_FRAG_SHADER ST_CONSTANTS: 1', output.getvalue())
        self.assertIn('SS_INDIRECT SB_VERT_SHADER ST_CONSTANTS: 1', output.getvalue())

    def test_multiline_block_with_blank_line_and_zero_shorthand(self):
        self.write('''bos:
  - iova: 0x3000
    size: 12
    data: !!ascii85 |
        z

        z
        z
''')
        payloads = list(SCAN.payloads(self.path))
        self.assertEqual(len(payloads), 1)
        self.assertEqual(SCAN.dwords(payloads[0][1]), [0, 0, 0])
        self.assertEqual(list(SCAN.scan(SCAN.dwords(payloads[0][1]))), [])

    def test_invalid_encoded_line_is_reported_not_silently_dropped(self):
        self.write('''bos:
  - iova: 0x4000
    size: 4
    data: !!ascii85 |
     ~~~~~
registers:
''')
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            SCAN.main(['devcore-cp-scan.py', str(self.path)])
        self.assertIn('undecodable payload, not scanned: 0x4000 size=4',
                      output.getvalue())

    def test_incomplete_word_is_rejected(self):
        for truncated in [base64.a85encode(b'\x12\x34\x56').decode(),
                          '!', encode([0x12345678]) + '!', 'z!']:
            with self.subTest(encoded=truncated):
                with self.assertRaisesRegex(ValueError, 'incomplete 32-bit word'):
                    SCAN.dwords([truncated])

    def test_empty_block_and_no_payload(self):
        for body, count in [('registers:\n', 0),
                            ('data: !!ascii85 |\nregisters:\n', 1)]:
            with self.subTest(body=body):
                self.write(body)
                payloads = list(SCAN.payloads(self.path))
                self.assertEqual(len(payloads), count)
                self.assertTrue(all(SCAN.dwords(chunks) == []
                                    for _, chunks in payloads))


class PacketTests(unittest.TestCase):
    def test_big_endian_word_decode(self):
        self.assertEqual(SCAN.dwords([encode([0xc0013000, 0x08340010])]),
                         [0xc0013000, 0x08340010])
        self.assertEqual(SCAN.dwords([' \tz\n', encode([0x12345678]), '\r\vz\f']),
                         [0, 0x12345678, 0])

    def test_truncated_and_short_packets_do_not_hide_later_packet(self):
        good = constant_load(6)
        # Advertised bodies longer than the payload, one-dword bodies, and
        # physically missing headers/bodies are not complete CP_LOAD_STATEs.
        for prefix in [[0xc0ff3000, 0, 0], [0xc0003000, 0]]:
            with self.subTest(prefix=prefix):
                hits = list(SCAN.scan(prefix + good))
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]['off'], len(prefix) * 4)
                self.assertEqual(hits[0]['block'], 6)
        self.assertEqual(list(SCAN.scan(good[:2])), [])
        self.assertEqual(list(SCAN.scan([0xc0033000, 0, 0])), [])

    def test_header_like_inline_data_is_not_reported_twice(self):
        words = [0xc0043000, 0, 1] + constant_load(6)
        hits = list(SCAN.scan(words))
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]['off'], 0)
        self.assertEqual(hits[0]['count'], 5)


if __name__ == '__main__':
    unittest.main()
