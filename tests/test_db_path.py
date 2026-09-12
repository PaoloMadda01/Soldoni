from pathlib import Path

import pytest

from soldoni.app import dashboard


@pytest.mark.parametrize("frozen", [False, True])
def test_db_path_uses_local_app_data_in_all_modes(monkeypatch, tmp_path, frozen):
    local_app_data = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local_app_data))
    monkeypatch.setattr(dashboard.sys, "frozen", frozen, raising=False)

    expected = local_app_data / "Soldoni" / "soldoni.db"

    assert Path(dashboard._db_path()) == expected
    assert expected.parent.is_dir()
