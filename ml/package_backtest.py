"""Dong goi phan mo phong cua OC (engines + sim + ml + du lieu FRN + mo hinh) thanh zip de chay backtest A/B tren Kaggle.

    python ml/package_backtest.py      -> ml/dist_bt/ops_chest_app.zip

Tren Kaggle (dataset `ops-chest-app`, Kaggle tu giai nen zip):
    pip install -q pydantic-settings
    cp -r <input>/app /kaggle/working/ && cd /kaggle/working
    python -m app.sim.backtest --frn --out /kaggle/working/backtest.json
Backtest khong dung DB/FastAPI: chi can numpy, lightgbm, pydantic-settings.
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "backend" / "app"
OUT = ROOT / "ml" / "dist_bt" / "ops_chest_app.zip"
INCLUDE = ["__init__.py", "config.py", "engines", "sim", "ml"]


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for item in INCLUDE:
            p = APP / item
            files = [p] if p.is_file() else [f for f in p.rglob("*") if f.is_file()]
            for f in files:
                if "__pycache__" in f.parts or f.suffix == ".pyc":
                    continue
                z.write(f, f.relative_to(APP.parent).as_posix())
                n += 1
    print(f"{OUT} ({n} file, {OUT.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
