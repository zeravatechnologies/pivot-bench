#!/usr/bin/env python3
"""Pivot Benchmark, the installed application: one window.

Starts the engine and the web app on a free local port (127.0.0.1 only; never
reachable from the network) and shows it in a desktop window. Data lives in
the user's data folder (mbench/paths.py). If the window toolkit is missing,
the app falls back to opening the system browser.

    python pivot_app.py            # the window
    python pivot_app.py --browser  # no window: start the server and open the browser
    python pivot_app.py --port N   # fixed port instead of a free one
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
# PyInstaller puts the bundled files next to the executable (onedir) or in _MEIPASS (onefile).
ROOT = getattr(sys, "_MEIPASS", HERE)
sys.path.insert(0, ROOT)

from mbench.version import APP_NAME, VERSION  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int) -> str:
    """Start the web app in a daemon thread; return its URL once it answers."""
    from mbench import paths
    from mbench.manager import RunManager
    from mbench.webapp import create_app
    import uvicorn

    data_dir = paths.user_data_dir()
    cfg_path = paths.ensure_user_config(ROOT, data_dir)
    paths.copy_defaults_if_missing(ROOT, data_dir)
    mgr = RunManager(ROOT, cfg_path)
    app = create_app(mgr)
    log_path = os.path.join(data_dir, "runs", "app.log")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True, name="pivot-web").start()
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/api/about", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {APP_NAME} {VERSION} started at {url}; data {data_dir}\n")
    return url


def show_window(url: str) -> int:
    from PySide6.QtCore import QUrl
    from PySide6.QtWidgets import QApplication, QMainWindow
    from PySide6.QtWebEngineWidgets import QWebEngineView

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    win = QMainWindow()
    win.setWindowTitle(f"{APP_NAME} {VERSION}")
    view = QWebEngineView()
    view.load(QUrl(url))
    win.setCentralWidget(view)
    win.resize(1280, 860)
    win.show()
    return app.exec()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--browser", action="store_true", help="open the system browser instead of a window")
    ap.add_argument("--port", type=int, default=None)
    ap.add_argument("--version", action="store_true")
    args = ap.parse_args(argv)
    if args.version:
        print(f"{APP_NAME} {VERSION}")
        return 0
    url = start_server(args.port or free_port())
    print(f"{APP_NAME} {VERSION}: {url}")
    if not args.browser:
        try:
            return show_window(url)
        except Exception as e:                      # no Qt / no WebEngine on this machine
            print(f"window unavailable ({e}); opening the browser instead")
    webbrowser.open(url)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
