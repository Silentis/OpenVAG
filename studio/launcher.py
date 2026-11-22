import asyncio
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
import traceback
import webbrowser
from pathlib import Path

import uvicorn

ROOT_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from studio.paths import LOG_DIR  # noqa: E402

# Fix PyInstaller --windowed (sys.stdout / sys.stderr are None in GUI mode)
_console_log = open(LOG_DIR / "app_console.log", "a", encoding="utf-8", buffering=1)
if sys.stdout is None:
    sys.stdout = _console_log
if sys.stderr is None:
    sys.stderr = _console_log

from studio.server import app  # noqa: E402

HOST = "127.0.0.1"
PORT = 8765
URL = f"http://{HOST}:{PORT}"

server_error = None


def wait_for_server(timeout: float = 12.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if server_error:
            return False
        try:
            with socket.create_connection((HOST, PORT), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def open_app_window():
    edge_paths = [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ]
    for edge in edge_paths:
        if Path(edge).exists():
            subprocess.Popen([edge, f"--app={URL}", "--window-size=1360,860"])
            return
    webbrowser.open(URL)


def start_uvicorn():
    global server_error
    try:
        config = uvicorn.Config(
            app,
            host=HOST,
            port=PORT,
            log_level="warning",
            log_config=None,  # Prevents NoneType.isatty() crash in --windowed .exe
        )
        server = uvicorn.Server(config)
        server.install_signal_handlers = lambda: None  # Thread-safe in background thread
        asyncio.run(server.serve())
    except Exception:
        server_error = traceback.format_exc()
        _console_log.write(server_error + "\n")
        _console_log.flush()


def main():
    t = threading.Thread(target=start_uvicorn, daemon=True)
    t.start()

    ready = wait_for_server()

    root = tk.Tk()
    root.title("OpenVAG Studio")
    root.geometry("380x150")
    root.resizable(False, False)
    root.configure(bg="#0f172a")

    if ready:
        status_text = f"Diagnostic Server Active\n{URL}"
        status_color = "#34d399"
        open_app_window()
    else:
        status_text = f"Server Failed to Start!\nCheck logs\\app_console.log"
        status_color = "#f87171"

    tk.Label(
        root,
        text=status_text,
        fg=status_color,
        bg="#0f172a",
        font=("Segoe UI", 10, "bold"),
        pady=14,
    ).pack()

    btn_frame = tk.Frame(root, bg="#0f172a")
    btn_frame.pack(pady=4)

    if ready:
        tk.Button(
            btn_frame, text="Open Diagnostic UI", command=open_app_window,
            bg="#0284c7", fg="white", relief="flat", padx=12, pady=5
        ).pack(side="left", padx=6)

    tk.Button(
        btn_frame, text="Exit App", command=root.destroy,
        bg="#dc2626", fg="white", relief="flat", padx=12, pady=5
    ).pack(side="left", padx=6)

    root.mainloop()


if __name__ == "__main__":
    main()