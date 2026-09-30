"""Check the real broker with a rejected request, without requesting a HAT."""
import errno
from pathlib import Path
import socket
import stat
import struct
import time

SOCKET = '/run/pocketfed-fpc-auth/token.sock'
DOMAIN = b'system_u:system_r:pocketfed_fpc_auth_t:s0'


def exchange(connection):
    pid, uid, gid = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
    if pid <= 0 or uid != 0 or gid != 0:
        raise RuntimeError('broker readiness peer is not root')
    context = connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERSEC, 256).rstrip(b'\0')
    if context != DOMAIN:
        raise RuntimeError('broker readiness peer is outside the dedicated domain')
    # Version 2 is invalid. Native process_request rejects it before opening
    # credential state or a TEE session. The zero challenge is also invalid.
    request = struct.pack('<4sIIQ', b'FPCA', 2, 1234, 0)
    deadline = time.monotonic() + 5
    connection.settimeout(5)
    connection.sendall(request)
    response = bytearray()
    while len(response) < 73:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('broker readiness response timed out')
        connection.settimeout(remaining)
        part = connection.recv(73 - len(response))
        if not part:
            raise RuntimeError('broker readiness response was incomplete')
        response.extend(part)
    if response != struct.pack('<i', -errno.EPROTO) + bytes(69):
        raise RuntimeError('broker readiness rejection was unexpected')
    return {'result': 'invalid version rejected before authorization',
            'peer_domain': DOMAIN.decode(), 'status': -errno.EPROTO,
            'token_requested': False}


def probe():
    directory = Path(SOCKET).parent.lstat()
    endpoint = Path(SOCKET).lstat()
    if not (stat.S_ISDIR(directory.st_mode) and stat.S_IMODE(directory.st_mode) == 0o700
            and directory.st_uid == directory.st_gid == 0
            and stat.S_ISSOCK(endpoint.st_mode) and stat.S_IMODE(endpoint.st_mode) == 0o600
            and endpoint.st_uid == endpoint.st_gid == 0):
        raise RuntimeError('broker readiness socket ownership or mode is unexpected')
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(5)
        connection.connect(SOCKET)
        return exchange(connection)
