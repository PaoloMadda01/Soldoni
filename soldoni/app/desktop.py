"""Launcher desktop per Soldoni: avvia il server Streamlit in locale (headless)
e lo mostra in una finestra nativa (pywebview). Entry point dell'eseguibile
prodotto con PyInstaller."""
import os
import sys
import socket
import threading
import time

import webview
import streamlit.web.bootstrap as bootstrap
import streamlit.config as config


def resource_path(rel: str) -> str:
    """Path di una risorsa, sia in sviluppo sia dentro il bundle PyInstaller."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, rel)


def find_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def wait_until_ready(port: int, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.5)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.2)
    raise RuntimeError(f"Server Streamlit non pronto su :{port} entro {timeout}s")


def _streamlit_flag_options(port: int) -> dict:
    """Opzioni di config da passare a Streamlit per girare in locale headless."""
    return {
        "server.headless": True,
        "server.port": port,
        "server.address": "127.0.0.1",
        "browser.gatherUsageStats": False,
        "global.developmentMode": False,
    }


def run_streamlit(port: int) -> None:
    script = resource_path("dashboard.py")
    flag_options = _streamlit_flag_options(port)
    # bootstrap.run NON legge le env var STREAMLIT_*: le opzioni vanno passate
    # come flag_options e applicate con load_config_options (come fa il CLI
    # `streamlit run`), altrimenti il server userebbe la porta 8501 di default
    # e binderebbe su tutte le interfacce (prompt firewall reti private).
    config._main_script_path = os.path.abspath(script)
    bootstrap.load_config_options(flag_options=flag_options)
    # I signal handler di Streamlit usano signal.signal(), che funziona solo nel
    # main thread: qui giriamo in un thread daemon, quindi li disattiviamo. Lo
    # shutdown lo gestiamo noi con os._exit(0) alla chiusura della finestra.
    bootstrap._set_up_signal_handler = lambda server: None
    bootstrap.run(script, False, [], flag_options)


def main() -> None:
    port = find_free_port()
    threading.Thread(target=run_streamlit, args=(port,), daemon=True).start()
    wait_until_ready(port)
    webview.create_window("Soldoni", f"http://127.0.0.1:{port}",
                          width=1280, height=800)
    webview.start()
    os._exit(0)


if __name__ == "__main__":
    main()
