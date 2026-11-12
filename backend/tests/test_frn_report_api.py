import shutil
from pathlib import Path

import pytest

from app.api import routes_core

DATA = Path(__file__).parent / "data"


@pytest.fixture()
def frn_files(tmp_path, monkeypatch):
    meta = tmp_path / "meta.json"
    report = tmp_path / "report.json"
    shutil.copy(DATA / "frn_meta_sample.json", meta)
    shutil.copy(DATA / "frn_report_sample.json", report)
    monkeypatch.setattr(routes_core, "FRN_META_FILE", meta)
    monkeypatch.setattr(routes_core, "FRN_REPORT_FILE", report)
    return meta, report


def test_default_paths_are_inside_app_package():
    app_dir = Path(routes_core.__file__).resolve().parent.parent
    assert routes_core.FRN_META_FILE == app_dir / "ml" / "artifacts" / "meta.json"
    assert routes_core.FRN_REPORT_FILE == app_dir / "sim" / "data" / "frn" / "report.json"


def test_frn_report_ok(client, staff, frn_files):
    r = client.get("/api/reports/ml/frn", headers=staff)
    assert r.status_code == 200, r.text
    d = r.json()
    assert set(d) == {"meta", "recovery_check", "eval_week_heldout", "rolling_heldout_bt", "gate",
                      "importance_q50", "elasticity"}
    assert "log" not in d
    assert d["meta"]["demo_store"] == 17
    assert d["meta"]["n_heldout_stores"] == 5
    assert d["eval_week_heldout"]["lightgbm"]["obs"]["all"]["coverage80"] == pytest.approx(0.774)
    assert d["gate"]["ban_it|deu"] is False
    assert d["elasticity"]["heldout_stores"]["all"]["ci90"] == [-1.61, -0.77]


def test_frn_report_meta_optional(client, staff, frn_files):
    frn_files[0].unlink()
    r = client.get("/api/reports/ml/frn", headers=staff)
    assert r.status_code == 200
    assert r.json()["meta"] is None


def test_frn_report_missing_is_404(client, staff, frn_files):
    frn_files[1].unlink()
    r = client.get("/api/reports/ml/frn", headers=staff)
    assert r.status_code == 404
    assert "Chưa có kết quả mô hình FRN" in r.json()["detail"]


def test_frn_report_requires_login(client, frn_files):
    assert client.get("/api/reports/ml/frn").status_code == 401


@pytest.fixture()
def frn_backtest_file(tmp_path, monkeypatch):
    f = tmp_path / "backtest.json"
    shutil.copy(DATA / "frn_backtest_sample.json", f)
    monkeypatch.setattr(routes_core, "FRN_BACKTEST_FILE", f)
    return f


def test_frn_backtest_default_path():
    app_dir = Path(routes_core.__file__).resolve().parent.parent
    assert routes_core.FRN_BACKTEST_FILE == app_dir / "sim" / "data" / "frn" / "backtest.json"


def test_frn_backtest_ok(client, staff, frn_backtest_file):
    r = client.get("/api/reports/backtest/frn", headers=staff)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["t0_date"] == "2024-05-26"
    assert d["summary"]["ml_vs_ewma"]["median"] < 0  # khong lam tron/tô hồng so am
    assert len(d["per_store"]) == 3
    assert d["scenarios"][2]["waste_a"] is None


def test_frn_backtest_missing_is_404(client, staff, frn_backtest_file):
    frn_backtest_file.unlink()
    r = client.get("/api/reports/backtest/frn", headers=staff)
    assert r.status_code == 404
    assert "python -m app.sim.backtest --frn" in r.json()["detail"]


def test_frn_backtest_requires_login(client, frn_backtest_file):
    assert client.get("/api/reports/backtest/frn").status_code == 401
