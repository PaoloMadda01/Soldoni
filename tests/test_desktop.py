import pytest

pytest.importorskip("webview")  # dipendenza solo per l'app desktop

import streamlit.config as st_config

from soldoni.app import desktop


def test_flag_options_usa_porta_scelta_e_loopback():
    opts = desktop._streamlit_flag_options(54321)
    assert opts["server.port"] == 54321
    assert opts["server.address"] == "127.0.0.1"
    assert opts["server.headless"] is True
    assert opts["browser.gatherUsageStats"] is False
    assert opts["global.developmentMode"] is False


def test_run_streamlit_applica_la_config_corretta(monkeypatch, tmp_path):
    # Regressione: le env var STREAMLIT_* non venivano lette da bootstrap.run,
    # quindi il server partiva su 8501 (non sulla porta scelta) e bindava su
    # tutte le interfacce (None). wait_until_ready interrogava la porta giusta
    # -> timeout; e il bind su 0.0.0.0 faceva scattare il prompt firewall.
    port = 54321
    captured = {}

    # bootstrap.run è bloccante (avvia il server): lo stubbiamo per catturare
    # solo le opzioni propagate, senza avviare nulla.
    monkeypatch.setattr(desktop.bootstrap, "run",
                        lambda script, is_hello, args, flag_options:
                        captured.update(flag_options=flag_options))
    monkeypatch.setattr(desktop, "resource_path", lambda rel: str(tmp_path / rel))

    try:
        desktop.run_streamlit(port)

        # Comportamento osservabile: la config di Streamlit riflette le opzioni.
        assert st_config.get_option("server.port") == port
        assert st_config.get_option("server.address") == "127.0.0.1"
        assert st_config.get_option("server.headless") is True
        assert st_config.get_option("browser.gatherUsageStats") is False
        # e le stesse opzioni sono propagate a bootstrap.run.
        assert captured["flag_options"]["server.port"] == port
    finally:
        # ripristina i default di config per non inquinare altri test.
        st_config.get_config_options(force_reparse=True)
