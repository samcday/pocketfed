#!/usr/bin/python3
"""Exercise readiness semantics independently of root, evdev and the display."""
from device_controls import ButtonSequence, EVENT, UP, DOWN, bit

s = ButtonSequence()
assert s.event(1, UP, 0) is None
assert s.event(1, UP, 2) is None
assert s.event(1, 116, 1) is None  # Power is not a readiness key.
assert s.event(1, UP, 1) is None
assert s.event(1, UP, 2) is None
assert s.event(1, UP, 0) == 'ready'
assert s.event(1, UP, 0) is None
s = ButtonSequence([UP, DOWN])
for key in (UP, DOWN):
 assert s.event(1, key, 1) is None
 assert s.event(1, key, 2) is None
 assert s.event(1, key, 0) is None
assert s.event(1, UP, 1) is None
assert s.event(1, UP, 0) == 'ready'
assert s.event(1, DOWN, 1) == 'cancel'
try: s.event(0, 3, 0)
except RuntimeError: pass
else: raise AssertionError('Dropped input must not be treated as readiness')
data = bytearray(96)
data[UP // 8] |= 1 << (UP % 8)
assert bit(data, UP) and not bit(data, DOWN)
assert EVENT.size == 24  # Native 64-bit host and AArch64 input_event ABI.
print('PASS fresh press/release, held keys, repeats, unrelated keys, cancellation and input overrun')
