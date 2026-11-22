import json
import os
import secrets
import time
from typing import Optional

_BASE_DIR = "/usr/src/app/downloads/.selection_pins"

_STALE_AFTER_SECONDS = 6 * 60 * 60


def _path(gid: str) -> str:
    return os.path.join(_BASE_DIR, f"{gid}.json")


def _is_safe_gid(gid: str) -> bool:
    if not gid or not isinstance(gid, str):
        return False
    return all(c.isalnum() or c in "-_" for c in gid)


def _read(gid: str) -> Optional[dict]:
    if not _is_safe_gid(gid):
        return None
    try:
        with open(_path(gid), "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _write(gid: str, payload: dict) -> bool:
    if not _is_safe_gid(gid):
        return False
    try:
        os.makedirs(_BASE_DIR, exist_ok=True)
        target = _path(gid)
        tmp = f"{target}.{os.getpid()}.{int(time.time() * 1000)}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, target)
        return True
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except (NameError, OSError):
            pass
        return False


def get_or_create_pin(gid: str, user_id: int) -> str:
    """Return the existing (unexpired) pin for this gid/user, else generate
    a fresh random 4-digit pin and persist it. The pin is only ever exposed
    to the task owner through the protected Pincode button."""
    existing = _read(gid)
    if existing and existing.get("user_id") == user_id:
        try:
            age = time.time() - existing.get("created_at", 0)
        except TypeError:
            age = _STALE_AFTER_SECONDS
        if age < _STALE_AFTER_SECONDS and str(existing.get("pin", "")).isdigit():
            return str(existing["pin"])
    pin = f"{secrets.randbelow(10000):04d}"
    _write(gid, {"pin": pin, "user_id": user_id, "created_at": time.time()})
    return pin


def get_pin(gid: str) -> Optional[str]:
    """Return the stored pin if present and unexpired, else None. Stale
    entries are removed so the web server rejects old links."""
    data = _read(gid)
    if data is None:
        return None
    try:
        stale = time.time() - data.get("created_at", 0) >= _STALE_AFTER_SECONDS
    except TypeError:
        stale = True
    pin = data.get("pin")
    if stale or not str(pin).isdigit():
        delete_pin(gid)
        return None
    return str(pin)


def delete_pin(gid: str) -> None:
    if not _is_safe_gid(gid):
        return
    try:
        os.remove(_path(gid))
    except (FileNotFoundError, OSError):
        pass


def cleanup_stale_pins(max_age_seconds: int = _STALE_AFTER_SECONDS) -> int:
    if not os.path.isdir(_BASE_DIR):
        return 0
    deadline = time.time() - max_age_seconds
    removed = 0
    try:
        for entry in os.scandir(_BASE_DIR):
            if not entry.is_file():
                continue
            name = entry.name
            if not (name.endswith(".json") or ".tmp" in name):
                continue
            try:
                if entry.stat().st_mtime < deadline:
                    os.remove(entry.path)
                    removed += 1
            except OSError:
                continue
    except OSError:
        return removed
    return removed
