"""Windows DPAPI storage. On other platforms use owner-only file permissions.

Machine scope is for the Eagle Eye service and requires provisioned directory
ACLs. DPAPI protects storage, not offline filesystem/snapshot rollback.
"""
import ctypes
from ctypes import wintypes
import os


def _dpapi(raw, *, decrypt=False, machine=False):
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = Blob(len(raw), buffer)
    output = Blob()
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        function = crypt.CryptUnprotectData
        function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output))
    else:
        function = crypt.CryptProtectData
        function.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p,
                             ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = function(ctypes.byref(source), 'AI-PACS licensing', None, None, None,
                      1 | (4 if machine else 0), ctypes.byref(output))
    if not ok:
        raise OSError('Windows could not protect or unlock licensing storage.')
    try:
        return ctypes.string_at(output.data, output.size)
    finally:
        kernel.LocalFree(output.data)


def protect(raw, *, machine=False):
    return b'DPAPI3\0' + _dpapi(raw, machine=machine) if os.name == 'nt' else b'PLAIN3\0' + raw


def unprotect(raw):
    if raw.startswith(b'DPAPI3\0') and os.name == 'nt':
        return _dpapi(raw[7:], decrypt=True)
    if raw.startswith(b'PLAIN3\0') and os.name != 'nt':
        return raw[7:]
    raise OSError('Licensing storage is unavailable under this account or platform.')
