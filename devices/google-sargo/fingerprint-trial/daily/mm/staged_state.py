"""Read libostree's staged GVariant using its existing GLib runtime library."""
import ctypes as C
from pathlib import Path


def read_staged(path=Path('/run/ostree/staged-deployment')):
    lib = C.CDLL('libglib-2.0.so.0')
    pointer = C.c_void_p
    signatures = {
        'g_bytes_new': (pointer, [pointer, C.c_size_t]),
        'g_bytes_unref': (None, [pointer]),
        'g_variant_type_new': (pointer, [C.c_char_p]),
        'g_variant_type_free': (None, [pointer]),
        'g_variant_new_from_bytes': (pointer, [pointer, pointer, C.c_int]),
        'g_variant_ref_sink': (pointer, [pointer]),
        'g_variant_unref': (None, [pointer]),
        'g_variant_is_normal_form': (C.c_int, [pointer]),
        'g_variant_get_type_string': (C.c_char_p, [pointer]),
        'g_variant_lookup_value': (pointer, [pointer, C.c_char_p, pointer]),
        'g_variant_get_boolean': (C.c_int, [pointer]),
        'g_variant_get_string': (C.c_char_p, [pointer, pointer]),
        'g_variant_n_children': (C.c_size_t, [pointer]),
        'g_variant_get_child_value': (pointer, [pointer, C.c_size_t]),
    }
    for name, (result, arguments) in signatures.items():
        function = getattr(lib, name)
        function.restype, function.argtypes = result, arguments
    data = path.read_bytes()
    assert 0 < len(data) < 1024 * 1024
    buffer = C.create_string_buffer(data)
    bytes_object = lib.g_bytes_new(buffer, len(data))
    kind = lib.g_variant_type_new(b'a{sv}')
    variant = lib.g_variant_ref_sink(lib.g_variant_new_from_bytes(kind, bytes_object, False))
    try:
        assert lib.g_variant_is_normal_form(variant), 'malformed staged GVariant'

        def value(parent, name, expected):
            child = lib.g_variant_lookup_value(parent, name.encode(), None)
            assert child, 'missing staged field: ' + name
            if lib.g_variant_get_type_string(child) != expected:
                lib.g_variant_unref(child)
                raise ValueError('unexpected staged field type: ' + name)
            return child

        def string(parent, name):
            child = value(parent, name, b's')
            try:
                return lib.g_variant_get_string(child, None).decode()
            finally:
                lib.g_variant_unref(child)

        target = value(variant, 'target', b'a{sv}')
        locked = value(variant, 'locked', b'b')
        # Direct OSTree staging can inherit arguments from merge-deployment
        # instead of recording an explicit kargs array.
        arguments = lib.g_variant_lookup_value(variant, b'kargs', None)
        merge = lib.g_variant_lookup_value(variant, b'merge-deployment', None)
        try:
            if arguments:
                assert lib.g_variant_get_type_string(arguments) == b'as'
            if merge:
                assert lib.g_variant_get_type_string(merge) == b'a{sv}'
            count = lib.g_variant_n_children(arguments) if arguments else 0
            assert count < 256
            strings = []
            for index in range(count):
                child = lib.g_variant_get_child_value(arguments, index)
                try:
                    strings.append(lib.g_variant_get_string(child, None).decode())
                finally:
                    lib.g_variant_unref(child)
            return {'locked': bool(lib.g_variant_get_boolean(locked)),
                    'target': {name: string(target, name) for name in ('name', 'bootcsum')},
                    'kargs': strings if arguments else None,
                    'merge_deployment': ({name: string(merge, name)
                                          for name in ('name', 'bootcsum')}
                                         if merge else None)}
        finally:
            for child in (arguments, merge, locked, target):
                if child:
                    lib.g_variant_unref(child)
    finally:
        lib.g_variant_unref(variant)
        lib.g_variant_type_free(kind)
        lib.g_bytes_unref(bytes_object)
