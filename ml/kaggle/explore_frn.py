"""Khao sat FreshRetailNet-50K (chay tren Kaggle). In ra mot JSON tom tat va ghi /kaggle/working/frn_explore.json.

    python explore_frn.py [--data-dir DIR]

Neu khong co --data-dir, tai 2 file parquet tu Hugging Face (can bat Internet cho notebook).
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HF = "https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/main/data/{}.parquet"


def fetch(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    data_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for split in ("train", "eval"):
        p = data_dir / f"{split}.parquet"
        if not p.exists():
            urllib.request.urlretrieve(HF.format(split), p)
        out.append(pd.read_parquet(p))
    return out[0], out[1]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("FRN_DIR", "/kaggle/working/frn"))
    args = ap.parse_args()
    tr, ev = fetch(Path(args.data_dir))
    r: dict = {"columns": {c: str(t) for c, t in tr.dtypes.items()}, "rows": {"train": len(tr), "eval": len(ev)}}
    for name, df in (("train", tr), ("eval", ev)):
        r[f"dates_{name}"] = [str(df["dt"].min()), str(df["dt"].max()), int(df["dt"].nunique())]
    key = ["store_id", "product_id"]
    r["n_series"] = int(tr[key].drop_duplicates().shape[0])
    r["n_stores"] = int(tr["store_id"].nunique())
    r["n_products"] = int(tr["product_id"].nunique())
    for c in ("city_id", "management_group_id", "first_category_id", "second_category_id", "third_category_id"):
        r[f"n_{c}"] = int(tr[c].nunique())
    per_store = tr.groupby("store_id")["product_id"].nunique()
    r["products_per_store"] = {"min": int(per_store.min()), "median": float(per_store.median()),
                               "max": int(per_store.max()), "top5": per_store.sort_values(ascending=False).head(5).to_dict()}
    s = tr["sale_amount"].to_numpy()
    pos = s[s > 0]
    r["sale_amount"] = {"zero_share": float((s == 0).mean()), "mean": float(s.mean()), "p50_pos": float(np.median(pos)),
                        "p90_pos": float(np.percentile(pos, 90)), "max": float(s.max()), "min_pos": float(pos.min())}
    # So ban co phai boi so cua mot don vi? (de suy ra he so quy doi)
    u = float(pos.min())
    ratio = pos / u
    r["sale_amount"]["share_integer_multiple_of_min"] = float(np.mean(np.abs(ratio - np.round(ratio)) < 1e-3))
    r["sale_amount"]["smallest_distinct"] = [float(x) for x in np.unique(np.round(pos, 6))[:10]]
    hs = np.stack(tr["hours_sale"].head(200000).to_numpy())
    st = np.stack(tr["hours_stock_status"].head(200000).to_numpy())
    cnt = tr["stock_hour6_22_cnt"].head(200000).to_numpy()
    r["hours_len"] = int(hs.shape[1])
    r["hours_sale_sum_vs_sale_amount_maxdiff"] = float(np.max(np.abs(hs.sum(1) - tr["sale_amount"].head(200000).to_numpy())))
    r["stock_status_values"] = sorted(int(x) for x in np.unique(st))
    for v in r["stock_status_values"]:
        r[f"corr_cnt_vs_count_status_{v}_6_22"] = float(np.corrcoef(cnt, (st[:, 6:22] == v).sum(1))[0, 1])
    r["stock_hour6_22_cnt"] = {"share_zero": float((tr["stock_hour6_22_cnt"] == 0).mean()),
                               "share_all16": float((tr["stock_hour6_22_cnt"] >= 16).mean()),
                               "mean": float(tr["stock_hour6_22_cnt"].mean())}
    r["discount"] = {"share_lt1": float((tr["discount"] < 1).mean()),
                     "quantiles": [float(x) for x in tr["discount"].quantile([0, .05, .25, .5, .75, .95, 1]).to_list()]}
    for c in ("holiday_flag", "activity_flag"):
        r[c] = {"share": float(tr[c].mean()), "dates_with_flag": int(tr.loc[tr[c] > 0, "dt"].nunique())}
    hol = tr.groupby("dt")["holiday_flag"].mean()
    r["holiday_dates"] = [str(d) for d in hol[hol > 0.5].index]
    r["activity_by_series_varies_same_day"] = float(tr.groupby(["store_id", "dt"])["activity_flag"].std().fillna(0).mean())
    # Ho so theo gio (ngay con hang du gio)
    full = (tr["stock_hour6_22_cnt"].head(200000).to_numpy() == 0)
    prof = hs[full].sum(0)
    r["hour_profile_full_instock"] = [round(float(x / prof.sum()), 4) for x in prof]
    js = json.dumps(r, ensure_ascii=False, indent=1, default=str)
    print(js)
    Path("/kaggle/working").mkdir(exist_ok=True, parents=True)
    Path("/kaggle/working/frn_explore.json").write_text(js)


if __name__ == "__main__":
    main()
