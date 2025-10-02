"""Secure string storage helpers leveraging Windows DPAPI when available."""
from __future__ import annotations

import base64
import os
import uuid
from typing import Optional

try:  # pragma: no cover - optional dependency
    import keyring  # type: ignore
    from keyring.errors import KeyringError  # type: ignore
except Exception:  # pragma: no cover - fallback when keyring missing
    keyring = None  # type: ignore
    KeyringError = Exception  # type: ignore

if os.name == "nt":  # pragma: no cover - Windows-specific
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p


SERVICE_NAME = "CodexFrontend"


def _protect_windows(plaintext: str) -> str:
    data = plaintext.encode("utf-16-le")
    buffer = ctypes.create_string_buffer(data)
    blob_in = DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    if not crypt32.CryptProtectData(ctypes.byref(blob_in), None, None, None, None, 0, ctypes.byref(blob_out)):
        raise RuntimeError("CryptProtectData failed")
    try:
        encrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def _unprotect_windows(token: str) -> Optional[str]:
    raw = base64.b64decode(token.encode("ascii"))
    buffer = ctypes.create_string_buffer(raw)
    blob_in = DATA_BLOB(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    blob_out = DATA_BLOB()
    ppsz_desc = wintypes.LPWSTR()
    if not crypt32.CryptUnprotectData(ctypes.byref(blob_in), ctypes.byref(ppsz_desc), None, None, None, 0, ctypes.byref(blob_out)):
        raise RuntimeError("CryptUnprotectData failed")
    try:
        decrypted = ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(blob_out.pbData)
        if ppsz_desc:
            kernel32.LocalFree(ppsz_desc)
    return decrypted.decode("utf-16-le")


def _protect_keyring(text: str, context: str) -> Optional[str]:  # pragma: no cover - requires keyring backend
    if not keyring:
        return None
    identifier = f"{context}:{uuid.uuid4().hex}"
    try:
        keyring.set_password(SERVICE_NAME, identifier, text)
    except KeyringError:
        return None
    return f"keyring:{identifier}"


def _unprotect_keyring(token: str) -> Optional[str]:  # pragma: no cover - requires keyring backend
    if not keyring:
        return None
    identifier = token[len("keyring:") :]
    try:
        return keyring.get_password(SERVICE_NAME, identifier)
    except KeyringError:
        return None


def _delete_keyring_token(token: str) -> None:  # pragma: no cover - requires keyring backend
    if not keyring:
        return
    identifier = token[len("keyring:") :]
    try:
        keyring.delete_password(SERVICE_NAME, identifier)
    except KeyringError:
        pass


def protect_string(text: str, context: str = "default") -> str:
    """Return an encoded token for the given string."""
    if not text:
        return ""
    if os.name == "nt":  # pragma: no cover - Windows specific
        try:
            return _protect_windows(text)
        except Exception:
            pass
    keyring_token = _protect_keyring(text, context)
    if keyring_token:
        return keyring_token
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def unprotect_string(token: Optional[str]) -> Optional[str]:
    """Decode a token produced by protect_string."""
    if not token:
        return None
    if token.startswith("keyring:"):
        value = _unprotect_keyring(token)
        if value is not None:
            return value
    if os.name == "nt":  # pragma: no cover - Windows specific
        try:
            return _unprotect_windows(token)
        except Exception:
            pass
    try:
        return base64.b64decode(token.encode("ascii")).decode("utf-8")
    except Exception:
        return None


def delete_token(token: Optional[str]) -> None:
    if not token:
        return
    if token.startswith("keyring:"):
        _delete_keyring_token(token)
