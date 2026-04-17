from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


_CRED_TYPE_GENERIC = 1
_ERROR_NOT_FOUND = 1168
_CRED_PERSIST_LOCAL_MACHINE = 2


class _FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class _CREDENTIAL_ATTRIBUTEW(ctypes.Structure):
    _fields_ = [
        ("Keyword", wintypes.LPWSTR),
        ("Flags", wintypes.DWORD),
        ("ValueSize", wintypes.DWORD),
        ("Value", ctypes.POINTER(ctypes.c_ubyte)),
    ]


class _CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", _FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.POINTER(_CREDENTIAL_ATTRIBUTEW)),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


_PCREDENTIALW = ctypes.POINTER(_CREDENTIALW)


def resolve_secret(*, env_var: str, credential_targets: list[str] | None = None) -> str | None:
    env_value = os.getenv(env_var)
    if env_value:
        return env_value
    for target in credential_targets or []:
        secret = read_windows_credential(target)
        if secret:
            return secret
    return None


def read_windows_credential(target: str) -> str | None:
    if os.name != "nt":
        return None
    for candidate in _candidate_targets(target):
        blob = _read_credential_blob(candidate)
        if blob:
            return _decode_blob(blob)
    return None


def write_windows_credential(
    target: str,
    secret: str,
    *,
    username: str = "api-token",
    comment: str | None = None,
) -> None:
    if os.name != "nt":
        raise OSError("Windows Credential Manager writes are only supported on Windows.")
    if not secret:
        raise ValueError("Credential secret must not be empty.")
    advapi32 = ctypes.WinDLL("Advapi32", use_last_error=True)
    cred_write = advapi32.CredWriteW
    cred_write.argtypes = [ctypes.POINTER(_CREDENTIALW), wintypes.DWORD]
    cred_write.restype = wintypes.BOOL

    secret_bytes = secret.encode("utf-16-le")
    blob = (ctypes.c_ubyte * len(secret_bytes)).from_buffer_copy(secret_bytes)
    credential = _CREDENTIALW()
    credential.Type = _CRED_TYPE_GENERIC
    credential.TargetName = target
    credential.Comment = comment
    credential.CredentialBlobSize = len(secret_bytes)
    credential.CredentialBlob = ctypes.cast(blob, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = _CRED_PERSIST_LOCAL_MACHINE
    credential.AttributeCount = 0
    credential.Attributes = None
    credential.TargetAlias = None
    credential.UserName = username
    success = cred_write(ctypes.byref(credential), 0)
    if not success:
        raise ctypes.WinError(ctypes.get_last_error())


def _candidate_targets(target: str) -> list[str]:
    if target.startswith("LegacyGeneric:target="):
        return [target]
    return [target, f"LegacyGeneric:target={target}"]


def _read_credential_blob(target: str) -> bytes | None:
    advapi32 = ctypes.WinDLL("Advapi32", use_last_error=True)
    cred_read = advapi32.CredReadW
    cred_read.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(_PCREDENTIALW),
    ]
    cred_read.restype = wintypes.BOOL
    cred_free = advapi32.CredFree
    cred_free.argtypes = [ctypes.c_void_p]
    credential = _PCREDENTIALW()
    success = cred_read(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(credential))
    if not success:
        error_code = ctypes.get_last_error()
        if error_code == _ERROR_NOT_FOUND:
            return None
        return None
    try:
        size = int(credential.contents.CredentialBlobSize)
        if size <= 0:
            return None
        return ctypes.string_at(credential.contents.CredentialBlob, size)
    finally:
        cred_free(credential)


def _decode_blob(blob: bytes) -> str:
    for encoding in ("utf-16-le", "utf-8", "utf-16-be", "latin-1"):
        try:
            decoded = blob.decode(encoding).rstrip("\x00")
            if decoded:
                return decoded
        except UnicodeDecodeError:
            continue
    return blob.decode("latin-1", errors="ignore").rstrip("\x00")
