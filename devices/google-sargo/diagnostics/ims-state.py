#!/usr/bin/python3
"""Read IMSA on one fresh QRTR socket (no third-party Python modules).

Only messages: client-local IMSA Bind (0x33), Get IMS Registration Status
(0x20), Get IMS Services Status (0x21). No network, bearer, call or power
changes. Endpoint port must come from qrtr-lookup, service 33 (IMSA).
Raw responses may contain subscriber identities; use --raw only for private
evidence. Discover the current endpoint with qrtr-lookup before each session.
For the investigated Sargo boot: --node 0 --port 78 --binding 0.

Definitions verified from upstream libqmi qmi-service-imsa.json and
qmi-enums-imsa.h; sockaddr_qrtr follows linux/qrtr.h and andersson/qrtr.
"""
import argparse
import ctypes
import datetime
import json
import os
import select
import socket
import struct
import sys
import time

INCLUDE_RAW = False

REGISTRATION = {0: "not-registered", 1: "registering", 2: "registered", 3: "limited-registered"}
SERVICE = {0: "unavailable", 1: "limited", 2: "available"}
TECHNOLOGY = {0: "wlan", 1: "wwan", 2: "interworking-wlan"}
class SockaddrQrtr(ctypes.Structure):
    _fields_ = [("family", ctypes.c_ushort), ("node", ctypes.c_uint32), ("port", ctypes.c_uint32)]

def emit(stage, **fields):
    if not INCLUDE_RAW:
        fields.pop("raw_response", None)
        fields.pop("raw_tlvs", None)
    print(json.dumps({"time": datetime.datetime.now().astimezone().isoformat(), "stage": stage, **fields}), flush=True)

def decode_tlvs(payload):
    fields = {}
    while payload:
        if len(payload) < 3:
            raise ValueError("truncated TLV header")
        kind, length = struct.unpack_from("<BH", payload)
        if len(payload) < 3 + length or kind in fields:
            raise ValueError("truncated or duplicate TLV")
        fields[kind] = payload[3:3 + length]
        payload = payload[3 + length:]
    return fields

def decode_values(msgid, fields):
    values = {"raw_tlvs": {f"0x{k:02x}": v.hex() for k, v in fields.items()}}
    if 2 not in fields or len(fields[2]) != 4:
        raise ValueError("missing operation result")
    status, error = struct.unpack("<HH", fields[2])
    values.update(operation_result=status, operation_error=error)
    if status:
        return values
    if msgid == 0x20:
        schema = {0x12: ("registration", REGISTRATION), 0x14: ("registration_technology", TECHNOLOGY)}
        if 0x11 in fields:
            values["registration_error_code"] = int.from_bytes(fields[0x11], "little")
        if 0x13 in fields:
            values["registration_error_message"] = fields[0x13].decode("utf-8", "replace")
    elif msgid == 0x21:
        schema = {0x10: ("sms", SERVICE), 0x11: ("voice", SERVICE), 0x12: ("video_telephony", SERVICE),
                  0x13: ("sms_technology", TECHNOLOGY), 0x14: ("voice_technology", TECHNOLOGY),
                  0x15: ("video_telephony_technology", TECHNOLOGY), 0x16: ("ue_to_tas", SERVICE),
                  0x17: ("ue_to_tas_technology", TECHNOLOGY), 0x18: ("video_share", SERVICE),
                  0x19: ("video_share_technology", TECHNOLOGY)}
    else:
        schema = {}
    for kind, (name, mapping) in schema.items():
        if kind in fields:
            if len(fields[kind]) != 4:
                raise ValueError(f"unexpected length for TLV {kind:#x}")
            number = int.from_bytes(fields[kind], "little")
            values[name] = {"value": number, "name": mapping.get(number, "unknown")}
    return values

def main():
    global INCLUDE_RAW
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node", type=int, default=0)
    parser.add_argument("--port", type=int)
    parser.add_argument("--binding", type=int, help="Explicit client binding; 0 worked in the Sargo capture")
    parser.add_argument("--raw", action="store_true", help="Include raw responses, which may contain subscriber identities")
    parser.add_argument("--no-bind", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    INCLUDE_RAW = args.raw
    if args.self_test:
        sample = bytes.fromhex("020400000000001204000200000014040001000000")
        decoded = decode_values(0x20, decode_tlvs(sample))
        assert decoded["registration"]["name"] == "registered"
        assert decoded["registration_technology"]["name"] == "wwan"
        assert ctypes.sizeof(SockaddrQrtr) == 12
        assert struct.pack("<BHHH", 0, 1, 0x33, 7).hex() == "00010033000700"
        emit("self-test-passed")
        return 0
    if args.port is None or args.port < 1 or args.port >= 0xfffffffe:
        parser.error("--port must be the observed IMSA service33 QRTR endpoint")
    if not args.no_bind and args.binding is None:
        parser.error("--binding is required unless --no-bind is selected")
    if args.binding is not None and (args.binding < 0 or args.binding > 0xffffffff):
        parser.error("binding outside uint32 range")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.sendto.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint]
    libc.sendto.restype = ctypes.c_ssize_t
    libc.recvfrom.argtypes = [ctypes.c_int, ctypes.c_void_p, ctypes.c_size_t, ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p]
    libc.recvfrom.restype = ctypes.c_ssize_t
    peer = SockaddrQrtr(42, args.node, args.port)
    with socket.socket(42, socket.SOCK_DGRAM, 0) as sock:
        emit("client-open", node=args.node, port=args.port, binding=args.binding, client_local_binding=not args.no_bind)
        def request(txn, msgid, payload=b""):
            packet = struct.pack("<BHHH", 0, txn, msgid, len(payload)) + payload
            result = libc.sendto(sock.fileno(), packet, len(packet), 0, ctypes.byref(peer), ctypes.sizeof(peer))
            if result != len(packet):
                raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
            deadline = time.monotonic() + 10
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not select.select([sock], [], [], remaining)[0]:
                    raise TimeoutError(f"IMSA message {msgid:#x} timed out")
                buf = ctypes.create_string_buffer(65536)
                source = SockaddrQrtr()
                source_len = ctypes.c_uint(ctypes.sizeof(source))
                size = libc.recvfrom(sock.fileno(), buf, len(buf), 0, ctypes.byref(source), ctypes.byref(source_len))
                if size < 0:
                    raise OSError(ctypes.get_errno(), os.strerror(ctypes.get_errno()))
                if (source.node, source.port) != (args.node, args.port):
                    continue
                raw = buf.raw[:size]
                if size < 7:
                    raise ValueError("truncated QMI response")
                flag, got_txn, got_msgid, length = struct.unpack_from("<BHHH", raw)
                if flag != 2 or got_txn != txn or got_msgid != msgid:
                    continue
                if length != size - 7:
                    raise ValueError("QMI payload length mismatch")
                values = decode_values(msgid, decode_tlvs(raw[7:]))
                emit(f"response-{msgid:#04x}", raw_response=raw.hex(), **values)
                return values["operation_result"] == 0
        if not args.no_bind and not request(1, 0x33, struct.pack("<BHI", 0x10, 4, args.binding)):
            return 1
        registration = request(2, 0x20)
        services = request(3, 0x21)
    emit("client-closed")
    return 0 if registration and services else 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        emit("error", error=str(error))
        sys.exit(1)
