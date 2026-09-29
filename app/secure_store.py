from __future__ import annotations

import ctypes
import os
import re
from ctypes import wintypes


TARGET_NAME = "Wuyou28/YU28ApiKey"
KEY_PATTERN = re.compile(r"^yu28_[0-9a-fA-F]{16}$")


class SecureStoreError(RuntimeError):
    pass


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def validate_yu28_api_key(value: str) -> str:
    key = str(value or "").strip()
    if not KEY_PATTERN.fullmatch(key):
        raise ValueError("YU28 API Key 格式不正确")
    return key


def _api():
    if os.name != "nt":
        raise SecureStoreError("安全凭据存储仅支持 Windows")
    advapi = ctypes.WinDLL("Advapi32", use_last_error=True)
    advapi.CredWriteW.argtypes = [ctypes.POINTER(_Credential), wintypes.DWORD]
    advapi.CredWriteW.restype = wintypes.BOOL
    advapi.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    advapi.CredReadW.restype = wintypes.BOOL
    advapi.CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    advapi.CredDeleteW.restype = wintypes.BOOL
    advapi.CredFree.argtypes = [ctypes.c_void_p]
    return advapi


def save_yu28_api_key(value: str) -> None:
    key = validate_yu28_api_key(value)
    encoded = key.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(encoded)).from_buffer_copy(encoded)
    credential = _Credential()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = TARGET_NAME
    credential.Comment = "YU28 API Key for 无忧28数据分析"
    credential.CredentialBlobSize = len(encoded)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE
    credential.UserName = "YU28"
    if not _api().CredWriteW(ctypes.byref(credential), 0):
        raise SecureStoreError(f"保存 Windows 凭据失败（{ctypes.get_last_error()}）")


def load_yu28_api_key() -> str:
    pointer = ctypes.POINTER(_Credential)()
    api = _api()
    if not api.CredReadW(TARGET_NAME, 1, 0, ctypes.byref(pointer)):
        error = ctypes.get_last_error()
        if error == 1168:  # ERROR_NOT_FOUND
            return ""
        raise SecureStoreError(f"读取 Windows 凭据失败（{error}）")
    try:
        credential = pointer.contents
        data = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        return validate_yu28_api_key(data.decode("utf-16-le"))
    finally:
        api.CredFree(pointer)


def delete_yu28_api_key() -> bool:
    api = _api()
    if api.CredDeleteW(TARGET_NAME, 1, 0):
        return True
    error = ctypes.get_last_error()
    if error == 1168:
        return False
    raise SecureStoreError(f"删除 Windows 凭据失败（{error}）")
