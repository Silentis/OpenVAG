import json
import os
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path
from typing import Any, Dict

from studio.config import APP_VERSION, UPDATE_JSON_URL
from studio.paths import APP_DIR, IS_FROZEN


def _parse_ver(v: str):
    return tuple(int(x) for x in v.strip().lstrip("v").split(".") if x.isdigit())


def check_for_update() -> Dict[str, Any]:
    if "YOUR_GITHUB_USER" in UPDATE_JSON_URL:
        return {"available": False, "current": APP_VERSION, "configured": False}

    try:
        req = urllib.request.Request(UPDATE_JSON_URL, headers={"User-Agent": "OpenVAG-Studio"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        remote_ver = str(data.get("version", APP_VERSION))
        if _parse_ver(remote_ver) > _parse_ver(APP_VERSION):
            return {
                "available": True,
                "current": APP_VERSION,
                "latest": remote_ver,
                "notes_lv": data.get("notes_lv", ""),
                "notes_en": data.get("notes_en", ""),
                "download_url": data.get("download_url", ""),
            }
        return {"available": False, "current": APP_VERSION, "latest": remote_ver}
    except Exception:
        return {"available": False, "current": APP_VERSION, "offline": True}


def download_and_apply_update(download_url: str) -> Dict[str, Any]:
    if not download_url:
        raise ValueError("Missing download_url in version.json")

    if not IS_FROZEN:
        return {"ok": False, "message": "Auto-replace only runs in the packaged .exe (running from Python source)."}

    current_exe = Path(sys.executable)
    new_exe = APP_DIR / f"{current_exe.stem}_new.exe"

    req = urllib.request.Request(download_url, headers={"User-Agent": "OpenVAG-Studio"})
    with urllib.request.urlopen(req, timeout=60.0) as resp, open(new_exe, "wb") as out:
        while True:
            chunk = resp.read(65536)
            if not chunk:
                break
            out.write(chunk)

    bat_path = Path(tempfile.gettempdir()) / "openvag_apply_update.bat"
    bat_script = f"""@echo off
timeout /t 2 /nobreak >nul
move /y "{new_exe}" "{current_exe}"
start "" "{current_exe}"
del "%~f0"
"""
    bat_path.write_text(bat_script, encoding="utf-8")

    DETACHED = 0x00000008 | 0x08000000
    subprocess.Popen(["cmd", "/c", str(bat_path)], creationflags=DETACHED)

    threading.Timer(0.6, lambda: os._exit(0)).start()
    return {"ok": True, "restarting": True}