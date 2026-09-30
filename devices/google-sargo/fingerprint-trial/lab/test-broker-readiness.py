#!/usr/bin/python3
"""Protocol/peer failure checks; no hardware, token or credential access."""
import errno
import socket
import struct
import unittest
from unittest.mock import patch
import broker_readiness as broker


class Connection:
    def __init__(self, uid=0, gid=0, pid=1, context=broker.DOMAIN, response=None):
        self.credentials = struct.pack('3i', pid, uid, gid)
        self.context = context
        self.response = struct.pack('<i', -errno.EPROTO) + bytes(69) if response is None else response
        self.sent = None

    def getsockopt(self, level, option, size):
        return self.credentials if option == socket.SO_PEERCRED else self.context

    def settimeout(self, seconds):
        assert 0 < seconds <= 5

    def sendall(self, data):
        self.sent = data

    def recv(self, size):
        # Deliberately fragmented: recv() need not return a complete frame.
        part, self.response = self.response[:1], self.response[1:]
        return part


class Readiness(unittest.TestCase):
    def test_fragmented_rejection_and_invalid_request(self):
        connection = Connection(context=broker.DOMAIN + b'\0')
        result = broker.exchange(connection)
        self.assertFalse(result['token_requested'])
        self.assertEqual(struct.unpack('<4sIIQ', connection.sent), (b'FPCA', 2, 1234, 0))

    def test_untrusted_peer_receives_nothing(self):
        for fields in ({'uid': 1234}, {'gid': 1234}, {'pid': 0},
                       {'context': b'system_u:system_r:unconfined_service_t:s0'}):
            with self.subTest(fields=fields):
                connection = Connection(**fields)
                with self.assertRaises(RuntimeError): broker.exchange(connection)
                self.assertIsNone(connection.sent)

    def test_bad_response_fails_closed(self):
        for response in (b'', bytes(72), bytes(73), struct.pack('<i', -errno.EINVAL) + bytes(69),
                         struct.pack('<i', -errno.EPROTO) + bytes(68) + b'X'):
            with self.subTest(length=len(response)):
                with self.assertRaises(RuntimeError): broker.exchange(Connection(response=response))

    def test_total_deadline(self):
        with patch.object(broker.time, 'monotonic', side_effect=(0, 6)):
            with self.assertRaises(TimeoutError): broker.exchange(Connection())


if __name__ == '__main__': unittest.main()
