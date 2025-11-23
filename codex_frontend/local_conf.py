"""Windows-side configuration helpers (password storage, etc)."""
from __future__ import annotations

import base64
import json
import time
from typing import Any, Dict, Optional

from . import secure_store, settings


def _read_conf() -> Dict[str, Any]:
    path = settings.conf_path()
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _write_conf(data: Dict[str, Any]) -> None:
    path = settings.conf_path()
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    tmp_path.replace(path)


def get_saved_password() -> Optional[str]:
    data = _read_conf()
    token = data.get("password_secure")
    if token:
        value = secure_store.unprotect_string(token)
        if value is not None:
            return value
    legacy = data.get("password_b64")
    if legacy:
        try:
            return base64.b64decode(legacy.encode("utf-8")).decode("utf-8")
        except Exception:
            return None
    return None


def save_password(pw: str) -> None:
    data = _read_conf()
    if not pw:
        secure_store.delete_token(data.get("password_secure"))
        data.pop("password_secure", None)
    else:
        token = secure_store.protect_string(pw, context="local_password")
        data["password_secure"] = token
    data.pop("password_b64", None)
    data["last_saved"] = int(time.time())
    _write_conf(data)


def clear_saved_password() -> None:
    data = _read_conf()
    secure_store.delete_token(data.get("password_secure"))
    data.pop("password_secure", None)
    data.pop("password_b64", None)
    _write_conf(data)


def read_all() -> Dict[str, Any]:
    return _read_conf()


def write_all(data: Dict[str, Any]) -> None:
    _write_conf(data)


def get_connection_settings() -> Dict[str, Any]:
    data = _read_conf().get("connection", {})
    remote = data.get("remote", {})
    password_token = remote.get("password_secure") or remote.get("password_b64")
    decoded_pw: Optional[str] = None
    if password_token:
        decoded_pw = secure_store.unprotect_string(password_token)
        if decoded_pw is None:
            try:
                decoded_pw = base64.b64decode(password_token.encode("utf-8")).decode("utf-8")
            except Exception:
                decoded_pw = None
    return {
        "mode": data.get("mode", "windows"),
        "host": remote.get("host", ""),
        "port": int(remote.get("port", 22)),
        "username": remote.get("username", "root"),
        "password": decoded_pw or "",
    }


def save_connection_settings(
    mode: str,
    host: str,
    port: int,
    username: str,
    password: str,
) -> None:
    data = _read_conf()
    old = data.get("connection", {}).get("remote", {}) if data.get("connection") else {}
    if old:
        secure_store.delete_token(old.get("password_secure"))
    if password:
        token = secure_store.protect_string(password, context=f"remote:{host}:{username}")
    else:
        token = ""
    data["connection"] = {
        "mode": mode,
        "remote": {
            "host": host,
            "port": int(port),
            "username": username,
            "password_secure": token,
        },
    }
    # Remove legacy field if present
    remote = data["connection"]["remote"]
    if "password_b64" in remote:
        remote.pop("password_b64")
    _write_conf(data)


def clear_remote_password() -> None:
    data = _read_conf()
    conn = data.get("connection", {})
    remote = conn.get("remote", {})
    secure_store.delete_token(remote.get("password_secure"))
    remote["password_secure"] = ""
    if "password_b64" in remote:
        remote["password_b64"] = ""
    data["connection"] = {"mode": conn.get("mode", "local"), "remote": remote}
    _write_conf(data)
