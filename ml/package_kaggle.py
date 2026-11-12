"""Gom ma can chay tren Kaggle vao ml/dist/ (thu muc phang) de tai len dataset `ops-chest-ml-code`.

    python ml/package_kaggle.py

train_frn.py tu dung lai goi app.engines tu cac file phang nay, nen Kaggle (luc huan luyen) va OC (luc chay that)
dung cung mot file ml_features.py.
"""
from __future__ import annotations

import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "ml" / "dist"
FILES = [
    ROOT / "ml" / "kaggle" / "train_frn.py",
    ROOT / "ml" / "kaggle" / "explore_frn.py",
    ROOT / "backend" / "app" / "engines" / "forecast.py",
    ROOT / "backend" / "app" / "engines" / "calendar.py",
    ROOT / "backend" / "app" / "engines" / "ml_features.py",
]


def main() -> None:
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir(parents=True)
    for f in FILES:
        # calendar.py nam phang canh script se che module calendar cua thu vien chuan -> doi ten
        name = "oc_calendar.py" if f.name == "calendar.py" else f.name
        shutil.copy2(f, DIST / name)
        print(DIST / name)


if __name__ == "__main__":
    main()
