import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG_PATH = ROOT / "studio" / "config.py"
VERSION_JSON_PATH = ROOT / "version.json"
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"


def run(cmd, check=True):
    print(f"> {' '.join(str(c) for c in cmd)}")
    res = subprocess.run(cmd, cwd=ROOT)
    if check and res.returncode != 0:
        sys.exit(res.returncode)
    return res.returncode


def get_current_version() -> str:
    text = CONFIG_PATH.read_text(encoding="utf-8")
    m = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    return m.group(1) if m else "1.0.0"


def bump_patch(ver: str) -> str:
    parts = [int(x) for x in ver.lstrip("v").split(".")]
    while len(parts) < 3:
        parts.append(0)
    parts[2] += 1
    return f"{parts[0]}.{parts[1]}.{parts[2]}"


def main():
    if not VENV_PY.exists():
        print("ERROR: .venv not found. Run build_exe.bat once first.")
        sys.exit(1)

    cur_ver = get_current_version()
    suggested = bump_patch(cur_ver)

    print(f"\n=== OpenVAG 1-Click Release & Push (Current: v{cur_ver}) ===")
    new_ver = input(f"New version [{suggested}]: ").strip() or suggested
    notes_lv = input("What changed (Latvian): ").strip() or "Uzlabojumi un kļūdu labojumi."
    notes_en = input(f"What changed (English) [{notes_lv}]: ").strip() or notes_lv

    # 1. Update studio/config.py
    cfg = CONFIG_PATH.read_text(encoding="utf-8")
    cfg = re.sub(r'APP_VERSION\s*=\s*"[^"]+"', f'APP_VERSION = "{new_ver}"', cfg)
    CONFIG_PATH.write_text(cfg, encoding="utf-8")

    # 2. Update version.json
    ver_data = {
        "version": new_ver,
        "notes_lv": notes_lv,
        "notes_en": notes_en,
        "download_url": "https://github.com/Silentis/OpenVAG/releases/latest/download/OpenVAG_Studio.exe",
    }
    VERSION_JSON_PATH.write_text(json.dumps(ver_data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    # 3. Kill running .exe if open, then rebuild
    subprocess.run(["taskkill", "/F", "/IM", "OpenVAG_Studio.exe"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    pyi_cmd = [
        str(VENV_PY), "-m", "PyInstaller",
        "--noconfirm", "--onefile", "--windowed", "--uac-admin",
        "--name", "OpenVAG_Studio",
        "--paths", ".",
        "--add-data", "studio\\static;studio\\static",
        "--hidden-import", "uvicorn.logging",
        "--hidden-import", "uvicorn.loops.auto",
        "--hidden-import", "uvicorn.protocols.http.auto",
        "--hidden-import", "uvicorn.protocols.websockets.auto",
        "--hidden-import", "uvicorn.lifespan.on",
        "--hidden-import", "serial.tools.list_ports",
        "studio\\launcher.py",
    ]
    if (ROOT / "blocks.json").exists():
        pyi_cmd.extend(["--add-data", "blocks.json;."])

    run(pyi_cmd)

    exe_path = ROOT / "dist" / "OpenVAG_Studio.exe"
    if not exe_path.exists():
        print("ERROR: EXE build failed.")
        sys.exit(1)

    # 4. Git commit, tag & push (handles first push too)
    tag = f"v{new_ver}"
    run(["git", "add", "-A"])
    run(["git", "commit", "-m", f"Release {tag}: {notes_en}"], check=False)
    run(["git", "tag", "-f", tag])
    run(["git", "push", "-u", "origin", "HEAD"])
    run(["git", "push", "-f", "origin", tag])

    # 5. Upload EXE to GitHub Releases
    rc = run([
        "gh", "release", "create", tag, str(exe_path),
        "--title", f"OpenVAG Studio {tag}",
        "--notes", f"LV: {notes_lv}\nEN: {notes_en}",
    ], check=False)

    if rc != 0:
        print("\nNote: Could not upload via 'gh'. Run once: winget install GitHub.cli && gh auth login")
    else:
        print(f"\nSUCCESS! {tag} is live on GitHub Releases.")


if __name__ == "__main__":
    main()