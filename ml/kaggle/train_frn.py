"""Huan luyen va danh gia du bao LightGBM tren FreshRetailNet-50K (chay tren Kaggle, CPU).

    python train_frn.py                 # chay day du, ghi /kaggle/working/out/
    python train_frn.py --smoke         # chay thu nhanh tren mau nho

Dau ra (/kaggle/working/out, nen zip de tai ve):
  artifacts/q10.txt q50.txt q90.txt         mo hinh chay that (cat o ngay 90)
  artifacts/bt_q10.txt bt_q50.txt bt_q90.txt mo hinh cho backtest (cat o ngay T0)
  artifacts/meta.json                        dac trung, moc cat, he so K, nhom dung ML, chi so
  frn/stores_daily.csv.gz                    du lieu theo ngay cua cac diem GIU LAI (khong dung de huan luyen)
  frn/dayparts.json  frn/elasticity.json  frn/report.json

Quy uoc FRN da kiem chung: hours_stock_status = 1 la HET hang; stock_hour6_22_cnt = so gio het hang 6-22h;
discount = gia ban / gia goc (1.0 = khong giam).
"""
from __future__ import annotations

import argparse
import gzip
import json
import math
import os
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.dont_write_bytecode = True


def _ensure_engines() -> None:
    """Dataset Kaggle phang (khong giu thu muc): dung lai goi app.engines tu cac file nam canh script nay."""
    if (HERE / "app" / "engines" / "ml_features.py").exists():
        sys.path.insert(0, str(HERE))
        return
    pkg = Path("/kaggle/working/_pkg") if Path("/kaggle").exists() else HERE / "_pkg"
    eng = pkg / "app" / "engines"
    eng.mkdir(parents=True, exist_ok=True)
    (pkg / "app" / "__init__.py").write_text("")
    (eng / "__init__.py").write_text("")
    for src, dst in (("forecast.py", "forecast.py"), ("oc_calendar.py", "calendar.py"), ("ml_features.py", "ml_features.py")):
        (eng / dst).write_text((HERE / src).read_text(encoding="utf-8"), encoding="utf-8")
    sys.path.insert(0, str(pkg))


_ensure_engines()

from app.engines.ml_features import CATEGORICAL, FEATURES, MAX_H, WINDOW, build_features, ewma_block  # noqa: E402

HF = "https://huggingface.co/datasets/Dingdong-Inc/FreshRetailNet-50K/resolve/main/data/{}.parquet"
K_SCALE = 10.0  # 1 don vi FRN (da quy doi) = 10 don vi hang o cua hang OC. Gia dinh, ghi trong docs.
DEMO_STORE = 18  # diem co nhieu mat hang nhat (164)
N_HELDOUT = 50
T0 = 59  # cot cuoi mo hinh backtest duoc thay (ngay thu 60)
CUTOFF = 89  # cot cuoi cua tap train FRN (ngay thu 90)
QUANTILES = (0.1, 0.5, 0.9)
Z90 = 1.2815515655446004
DAYPARTS = ((6, 11), (11, 14), (14, 17), (17, 22))
LOG = []


def log(*a):
    msg = " ".join(str(x) for x in a)
    LOG.append(f"[{time.strftime('%H:%M:%S')}] {msg}")
    print(LOG[-1], flush=True)


# ---------------------------------------------------------------- du lieu
def load(data_dir: Path, smoke: bool) -> pd.DataFrame:
    data_dir.mkdir(parents=True, exist_ok=True)
    parts = []
    for split in ("train", "eval"):
        p = data_dir / f"{split}.parquet"
        if not p.exists():
            local = list(Path("/kaggle/input").rglob(f"{split}.parquet")) if Path("/kaggle/input").exists() else []
            if local:
                p = local[0]
            else:
                log("tai", split)
                urllib.request.urlretrieve(HF.format(split), p)
        parts.append(pd.read_parquet(p))
    df = pd.concat(parts, ignore_index=True)
    if smoke:
        keep = df[["store_id"]].drop_duplicates().sample(40, random_state=1)["store_id"].tolist() + [DEMO_STORE]
        df = df[df["store_id"].isin(keep)]
    return df.sort_values(["store_id", "product_id", "dt"]).reset_index(drop=True)


class Panel:
    """Mang (chuoi x ngay) tu bang FRN dang dai."""

    def __init__(self, df: pd.DataFrame):
        self.dates = [date.fromisoformat(str(d)[:10]) for d in sorted(df["dt"].unique())]
        T = len(self.dates)
        keys = df[["store_id", "product_id"]].drop_duplicates().reset_index(drop=True)
        n = len(keys)
        idx = {k: i for i, k in enumerate(zip(keys.store_id, keys.product_id))}
        di = {d: j for j, d in enumerate(sorted(df["dt"].unique()))}
        rows = np.fromiter((idx[k] for k in zip(df.store_id, df.product_id)), dtype=np.int64, count=len(df))
        cols = df["dt"].map(di).to_numpy()
        if len(df) != n * T:
            raise SystemExit(f"Bang khong day du: {len(df)} dong, {n} chuoi x {T} ngay")
        self.n, self.T = n, T
        self.store = keys.store_id.to_numpy()
        self.product = keys.product_id.to_numpy()

        def grid(col, dtype=np.float64):
            a = np.zeros((n, T), dtype=dtype)
            a[rows, cols] = df[col].to_numpy()
            return a

        self.sale = grid("sale_amount")
        self.stock_hours = grid("stock_hour6_22_cnt", np.int16)
        self.discount = np.clip(grid("discount"), 0, 1.5)
        self.activity = grid("activity_flag")
        hol = df.groupby("dt")["holiday_flag"].mean().sort_index().to_numpy()
        self.holiday = np.concatenate([(hol > 0.5).astype(float), np.zeros(MAX_H)])
        self.weekday = np.array([d.weekday() for d in self.dates] + [(self.dates[-1] + timedelta(days=i + 1)).weekday()
                                                                     for i in range(MAX_H)])
        first = df.groupby(["store_id", "product_id"], sort=False).first().reindex(list(zip(keys.store_id, keys.product_id)))
        self.city = first["city_id"].to_numpy()
        self.statics = first[["management_group_id", "first_category_id", "second_category_id"]].to_numpy()
        self.cat3 = first["third_category_id"].to_numpy()
        self.hours = np.zeros((n, T, 24), dtype=np.float32)
        self.out = np.zeros((n, T, 24), dtype=np.int8)
        self.hours[rows, cols] = np.stack(df["hours_sale"].to_numpy()).astype(np.float32)
        self.out[rows, cols] = np.stack(df["hours_stock_status"].to_numpy()).astype(np.int8)
        self.S = self.stock_hours > 0
        pad = np.ones((n, MAX_H))
        self.discount_p = np.hstack([self.discount, pad])
        self.activity_p = np.hstack([self.activity, np.zeros((n, MAX_H))])


# ---------------------------------------------------------------- khoi phuc nhu cau ngay het hang
def hour_profiles(P: Panel) -> np.ndarray:
    """Ho so ban theo gio cua tung chuoi, chi tu ngay con hang du gio; it ngay thi dung ho so cua nhom cat1."""
    full = (P.stock_hours == 0)[:, :, None]
    s = (P.hours * full).sum(1)  # (n, 24)
    days = full[:, :, 0].sum(1)
    cat = P.statics[:, 1]
    prof = np.zeros_like(s)
    for c in np.unique(cat):
        m = cat == c
        cs = s[m].sum(0)
        prof[m] = cs / cs.sum() if cs.sum() > 0 else 1 / 24
    ok = (days >= 5) & (s.sum(1) > 0)
    prof[ok] = s[ok] / s[ok].sum(1, keepdims=True)
    return prof


def recover(P: Panel, prof: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Nhu cau uoc tinh = ban / ty trong nhu cau roi vao cac gio con hang. Tra ve (demand, share_instock)."""
    share = np.einsum("ntk,nk->nt", 1 - P.out.astype(np.float32), prof)
    d = P.sale / np.maximum(share, 0.3)
    severe = share < 0.3
    d = np.where(P.stock_hours == 0, P.sale, d)
    # Ngay het hang gan ca ngay: lay TB cung thu cua ngay khong nang
    for wd in range(7):
        cols = np.where(P.weekday[:P.T] == wd)[0]
        sub = np.where(severe[:, cols], np.nan, d[:, cols])
        mean = np.nanmean(np.where(np.isnan(sub).all(1, keepdims=True), 0, sub), axis=1)
        d[:, cols] = np.where(severe[:, cols], np.maximum(P.sale[:, cols], mean[:, None]), d[:, cols])
    return d, share


def recovery_check(P: Panel, prof: np.ndarray, rng: np.random.Generator) -> dict:
    """Che gio tren ngay con hang du gio (gia lap het hang tu gio k den het ngay) roi so voi so that."""
    i, j = np.where(P.stock_hours[:, :CUTOFF + 1] == 0)
    pick = rng.choice(len(i), size=min(200_000, len(i)), replace=False)
    i, j = i[pick], j[pick]
    k = rng.integers(12, 21, size=len(i))
    hrs = np.arange(24)[None, :]
    mask = hrs >= k[:, None]
    seen = (P.hours[i, j] * ~mask).sum(1)
    share = (prof[i] * ~mask).sum(1)
    est = seen / np.maximum(share, 0.3)
    true = P.sale[i, j]
    naive = seen
    return {"n": int(len(i)), "wape_recovered": float(np.abs(est - true).sum() / true.sum()),
            "bias_recovered": float((est - true).sum() / true.sum()),
            "wape_sales_as_demand": float(np.abs(naive - true).sum() / true.sum()),
            "bias_sales_as_demand": float((naive - true).sum() / true.sum())}


# ---------------------------------------------------------------- du bao EWMA cua OC (dac trung + moc so sanh)
_POOL_P = None


def _ewma_job(args):
    idx, t, use_stockout = args
    P = _POOL_P
    S = P.S[idx] if use_stockout else np.zeros_like(P.S[idx])
    return ewma_block(P.sale[idx], S, t, P.dates[t], K_SCALE)


def ewma_all(P: Panel, series: np.ndarray, origins, use_stockout: bool = True) -> dict:
    """Du bao EWMA cho moi moc t, tinh song song tren moi nhan CPU. Tra ve {t: (mid (n, H), sigma (n,))}."""
    global _POOL_P
    import multiprocessing as mp
    _POOL_P = P
    ncpu = os.cpu_count() or 1
    chunks = [c for c in np.array_split(series, max(1, ncpu * 2)) if len(c)]
    jobs = [(c, t, use_stockout) for t in origins for c in chunks]
    with mp.get_context("fork").Pool(ncpu) as pool:
        res = pool.map(_ewma_job, jobs, chunksize=1)
    out = {}
    k = 0
    for t in origins:
        parts = res[k:k + len(chunks)]
        k += len(chunks)
        out[t] = (np.vstack([x[0] for x in parts]), np.concatenate([x[1] for x in parts]))
    return out


# ---------------------------------------------------------------- tap mau
def samples(P: Panel, D: np.ndarray, share: np.ndarray, series: np.ndarray, origins, target_max: int, ew: dict):
    """Chuoi da quy ve gia goc (giong chuoi `demand` cua OC). Dich = nhu cau da khoi phuc / muc nen, chi ngay het hang
    khong nang (cac gio con hang chiem >= 50% nhu cau)."""
    Xs, ys, keep_t = [], [], []
    for t in origins:
        X, level = build_features(P.sale[series], P.S[series], t, range(1, MAX_H + 1), P.weekday, P.holiday,
                                  P.statics[series], ewma=ew[t])
        n = len(series)
        for h in range(1, MAX_H + 1):
            d = t + h
            if d > target_max:
                continue
            rows = slice((h - 1) * n, h * n)
            ok = (level > 0) & (share[series, d] >= 0.5)
            Xs.append(X[rows][ok])
            ys.append((D[series, d] / np.where(level > 0, level, 1))[ok])
            keep_t.append(np.full(ok.sum(), d))
    return np.vstack(Xs), np.concatenate(ys).astype(np.float32), np.concatenate(keep_t)


BASE_PARAMS = dict(feature_fraction=0.8, bagging_fraction=0.7, bagging_freq=1, lambda_l2=1.0, max_bin=255, verbose=-1,
                   seed=7)
SEARCH = [  # cau hinh do tren mau con, chon theo pinball q50 cua 7 ngay cuoi
    dict(num_leaves=63, min_data_in_leaf=200),
    dict(num_leaves=127, min_data_in_leaf=200),
    dict(num_leaves=255, min_data_in_leaf=100),
    dict(num_leaves=255, min_data_in_leaf=500, lambda_l2=10.0),
    dict(num_leaves=511, min_data_in_leaf=300, feature_fraction=0.7),
    dict(num_leaves=127, min_data_in_leaf=50, feature_fraction=0.6),
    dict(num_leaves=255, min_data_in_leaf=200, max_bin=511),
]
PARAM_KEYS = ("num_leaves", "min_data_in_leaf", "lambda_l2", "feature_fraction", "max_bin")


class Budget:
    """Phien Kaggle toi da 12 gio: dung o han an toan de con thoi gian ghi va nen ket qua."""

    def __init__(self, hours: float):
        self.t0 = time.time()
        self.limit = hours * 3600

    def used(self) -> float:
        return time.time() - self.t0

    def left(self) -> float:
        return self.limit - self.used()


def _lgb_data(X, y, ref=None, max_bin: int = 255):
    """feature_pre_filter=False: cho phep doi min_data_in_leaf giua cac lan hoc tren cung Dataset."""
    import lightgbm as lgb
    if ref is None:
        cat_idx = [FEATURES.index(c) for c in CATEGORICAL]
        return lgb.Dataset(X, y, feature_name=list(FEATURES), categorical_feature=cat_idx, free_raw_data=False,
                           params={"feature_pre_filter": False, "max_bin": max_bin})
    return lgb.Dataset(X, y, reference=ref)


def search_params(X, y, td, valid_from: int, smoke: bool, budget: Budget, rng) -> tuple[dict, list]:
    """Do sieu tham so cho q50 tren mau con 30% so dong, toc do hoc cao de nhanh."""
    import lightgbm as lgb
    pick = rng.random(len(y)) < 0.3
    tr, va = pick & (td < valid_from), pick & (td >= valid_from)
    Xtr, ytr, Xva, yva = X[tr], y[tr], X[va], y[va]
    results = []
    for cfg in (SEARCH[:2] + SEARCH[-1:] if smoke else SEARCH):  # chay thu: van di qua moi nhanh ma
        # Dataset rieng cho moi cau hinh (max_bin la tham so cua Dataset)
        dtr = _lgb_data(Xtr, ytr, max_bin=cfg.get("max_bin", 255))
        dva = _lgb_data(Xva, yva, dtr)
        if not smoke and budget.left() < 8.5 * 3600:  # giu phan lon thoi gian cho mo hinh that
            log("dung do tham so de giu thoi gian")
            break
        params = {**BASE_PARAMS, **cfg, "objective": "quantile", "alpha": 0.5, "learning_rate": 0.1,
                  "num_threads": os.cpu_count()}
        t0 = time.time()
        m = lgb.train(params, dtr, num_boost_round=20 if smoke else 3000, valid_sets=[dva],
                      callbacks=[lgb.early_stopping(100, verbose=False), lgb.log_evaluation(0)])
        loss = float(m.best_score["valid_0"]["quantile"])
        results.append({**cfg, "valid_pinball50": loss, "rounds": m.best_iteration, "seconds": round(time.time() - t0)})
        log(f"do tham so {cfg}: pinball {loss:.5f}, {m.best_iteration} vong, {time.time() - t0:.0f}s")
    if not results:
        return dict(SEARCH[1]), results
    best = min(results, key=lambda r: r["valid_pinball50"])
    return {k: v for k, v in best.items() if k in PARAM_KEYS}, results


def train_quantiles(X, y, td, valid_from: int, smoke: bool, prefix: str, outdir: Path, params: dict, lr: float,
                    budget: Budget, reserve_s: float) -> tuple[dict, dict]:
    """Moi phan vi: hoc voi kiem tra som tren 7 ngay cuoi. Mo hinh luu ngay sau khi xong (khong mat neu het gio)."""
    import lightgbm as lgb
    tr, va = td < valid_from, td >= valid_from
    dtr = _lgb_data(X[tr], y[tr], max_bin=params.get("max_bin", 255))
    dva = _lgb_data(X[va], y[va], dtr)
    models, info = {}, {}
    for k, q in enumerate((0.5, 0.1, 0.9)):  # q50 truoc: quan trong nhat
        p = {**BASE_PARAMS, **params, "objective": "quantile", "alpha": q, "learning_rate": lr,
             "num_threads": os.cpu_count()}
        t0 = time.time()
        # Chia deu thoi gian con lai (tru phan du tru) cho cac phan vi chua hoc
        stop_at = budget.used() + max(600.0, (budget.left() - reserve_s) / (3 - k))

        def guard(env, stop_at=stop_at):
            if budget.used() > stop_at:
                raise lgb.callback.EarlyStopException(env.iteration, env.evaluation_result_list)

        m = lgb.train(p, dtr, num_boost_round=30 if smoke else 20000, valid_sets=[dva],
                      callbacks=[lgb.early_stopping(300, verbose=False), lgb.log_evaluation(0), guard])
        name = f"{prefix}q{int(q * 100)}"
        best = m.best_iteration or m.current_iteration()
        m.save_model(str(outdir / f"{name}.txt"), num_iteration=best)
        info[name] = {"rounds": best, "seconds": round(time.time() - t0),
                      "valid_pinball": float(m.best_score["valid_0"]["quantile"]) if m.best_score else None}
        log(f"{name}: {best} vong, {time.time() - t0:.0f}s, {tr.sum()} dong train, {va.sum()} dong valid")
        models[q] = lgb.Booster(model_file=str(outdir / f"{name}.txt"))
    return models, info


def refit_all(X, y, prefix: str, outdir: Path, params: dict, lr: float, info: dict, budget: Budget,
              reserve_s: float) -> list:
    """Hoc lai tren TOAN BO du lieu (ca 7 ngay cuoi - gan ngay du bao nhat) voi so vong tot nhat x 1.1.
    Chi lam khi con du gio; neu khong giu mo hinh da kiem tra som."""
    import lightgbm as lgb
    done = []
    dall = _lgb_data(X, y, max_bin=params.get("max_bin", 255))
    for q in (0.5, 0.1, 0.9):
        name = f"{prefix}q{int(q * 100)}"
        need = info[name]["seconds"] * 1.35
        if budget.left() - reserve_s < need:
            log(f"bo qua hoc lai {name}: can ~{need / 60:.0f} phut, con {budget.left() / 60:.0f} phut")
            continue
        p = {**BASE_PARAMS, **params, "objective": "quantile", "alpha": q, "learning_rate": lr,
             "num_threads": os.cpu_count()}
        t0 = time.time()
        m = lgb.train(p, dall, num_boost_round=max(50, int(info[name]["rounds"] * 1.1)))
        m.save_model(str(outdir / f"{name}.txt"))
        info[name]["refit_all_rounds"] = m.current_iteration()
        done.append(name)
        log(f"hoc lai {name} tren toan bo: {m.current_iteration()} vong, {time.time() - t0:.0f}s")
    return done


def predict(models: dict, P: Panel, series, t: int, ew: dict):
    """Du bao nhu cau o GIA GOC tu chuoi da quy ve gia goc - dung nhu OC goi mo hinh."""
    X, level = build_features(P.sale[series], P.S[series], t, range(1, MAX_H + 1), P.weekday, P.holiday,
                              P.statics[series], ewma=ew[t])
    n = len(series)
    out = {}
    for q, m in models.items():
        r = m.predict(X).reshape(MAX_H, n).T  # (n, h)
        out[q] = np.maximum(r, 0) * level[:, None]
    return np.minimum(out[0.1], out[0.5]), out[0.5], np.maximum(out[0.9], out[0.5])


# ---------------------------------------------------------------- moc so sanh
def ewma_pred(ew: dict, t: int):
    mid, sig = ew[t]
    return np.maximum(mid - Z90 * sig[:, None], 0), mid, mid + Z90 * sig[:, None]


def naive(P: Panel, series, t: int):
    mid = np.stack([P.sale[series, t + h - 7] for h in range(1, MAX_H + 1)], 1)
    return None, mid, None


def ma28(P: Panel, series, t: int):
    m = P.sale[series, t - 27:t + 1].mean(1)
    return None, np.repeat(m[:, None], MAX_H, 1), None


# ---------------------------------------------------------------- chi so
def score(y, lo, mid, hi) -> dict:
    s = float(y.sum())
    r = {"n": int(y.size), "wape": float(np.abs(mid - y).sum() / s), "bias": float((mid - y).sum() / s)}

    def pin(q, f):
        e = y - f
        return float(np.maximum(q * e, (q - 1) * e).sum() / s)

    r["pinball50"] = pin(0.5, mid)
    if lo is not None:
        r["pinball10"], r["pinball90"] = pin(0.1, lo), pin(0.9, hi)
        r["coverage80"] = float(((y >= lo) & (y <= hi)).mean())
    return r


def evaluate(P, D, share, series, origins, methods: dict, segments: np.ndarray) -> dict:
    """Danh gia tren 3 tap dich: 'obs' = ngay con hang du gio (so ban = nhu cau, khong qua uoc luong nao); 'rec' = moi
    ngay het hang khong nang (nhu cau da khoi phuc); 'fp' = ngay con hang du gio VA ban gia goc, khong khuyen mai."""
    acc = {name: {"obs": [], "rec": [], "fp": []} for name in methods}
    seg_rows = {"obs": [], "rec": [], "fp": []}
    for t in origins:
        for name, fn in methods.items():
            lo, mid, hi = fn(series, t)
            for h in range(1, MAX_H + 1):
                d = t + h
                if d >= P.T:
                    continue
                for kind in ("obs", "rec", "fp"):
                    if kind == "obs":
                        ok = P.stock_hours[series, d] == 0
                    elif kind == "fp":
                        ok = (P.stock_hours[series, d] == 0) & P.fullprice[series, d]
                    else:
                        ok = share[series, d] >= 0.5
                    y = (D if kind == "rec" else P.sale)[series, d]
                    acc[name][kind].append((y[ok], None if lo is None else lo[ok, h - 1], mid[ok, h - 1],
                                            None if hi is None else hi[ok, h - 1]))
                    if name == next(iter(methods)):
                        seg_rows[kind].append(segments[series][ok])
    out = {}
    for name, kinds in acc.items():
        out[name] = {}
        for kind, parts in kinds.items():
            y = np.concatenate([p[0] for p in parts])
            lo = None if parts[0][1] is None else np.concatenate([p[1] for p in parts])
            mid = np.concatenate([p[2] for p in parts])
            hi = None if parts[0][3] is None else np.concatenate([p[3] for p in parts])
            seg = np.concatenate(seg_rows[kind])
            res = {"all": score(y, lo, mid, hi)}
            for sname in np.unique(seg):
                m = seg == sname
                res[str(sname)] = score(y[m], None if lo is None else lo[m], mid[m], None if hi is None else hi[m])
            out[name][kind] = res
    return out


# ---------------------------------------------------------------- do co gian, khung gio
def elasticity(P: Panel, series) -> dict:
    """Ban tang ~ 1 + e * muc giam, chi ngay con hang du gio. Nen = TB cung thu, gia goc, khong khuyen mai."""
    S = series
    full = P.stock_hours[S, :CUTOFF + 1] == 0
    disc = P.discount[S, :CUTOFF + 1]
    act = P.activity[S, :CUTOFF + 1]
    sale = P.sale[S, :CUTOFF + 1]
    wd = P.weekday[:CUTOFF + 1]
    base_ok = full & (disc >= 0.99) & (act == 0)
    base = np.full(sale.shape, np.nan)
    for w in range(7):
        c = wd == w
        num = (sale[:, c] * base_ok[:, c]).sum(1)
        cnt = base_ok[:, c].sum(1)
        base[:, c] = np.where(cnt >= 2, num / np.maximum(cnt, 1), np.nan)[:, None]
    # Chi ngay giam gia KHONG kem co khuyen mai: tach tac dong cua gia khoi tac dong quang ba
    deal = full & (disc <= 0.95) & (disc >= 0.3) & (act == 0) & ~np.isnan(base) & (base > 0)
    promo = full & (disc >= 0.99) & (act == 1) & ~np.isnan(base) & (base > 0)
    d = 1 - disc
    r = np.clip(sale / np.where(base > 0, base, 1), 0, 10) - 1
    grp = P.statics[S, 0]

    def fit(mask_rows):
        m = deal & mask_rows[:, None]
        dd, rr = d[m], r[m]
        return float((dd * rr).sum() / (dd * dd).sum()) if dd.size > 50 else None, int(dd.size)

    rng = np.random.default_rng(3)
    allrows = np.ones(len(S), bool)
    e, n = fit(allrows)
    boots = []
    for _ in range(200):
        pick = np.zeros(len(S), bool)
        pick[rng.integers(0, len(S), len(S))] = True
        b, _ = fit(pick)
        if b is not None:
            boots.append(b)
    res = {"all": {"e": e, "n": n, "ci90": [float(np.percentile(boots, 5)), float(np.percentile(boots, 95))]
                   if boots else None}, "by_group": {}}
    for g in np.unique(grp):
        eg, ng = fit(grp == g)
        res["by_group"][str(int(g))] = {"e": eg, "n": ng}
    # Khong tham so: muc ban tang trung binh theo bac giam gia (de thay hinh dang, khong chi mot he so)
    res["by_depth"] = []
    for lo, hi in ((0.05, 0.15), (0.15, 0.25), (0.25, 0.4), (0.4, 0.7)):
        m = deal & (d >= lo) & (d < hi)
        if m.sum() > 50:
            res["by_depth"].append({"depth": [lo, hi], "uplift_mean": float(r[m].mean()), "uplift_median": float(np.median(r[m])),
                                    "n": int(m.sum())})
    res["activity_uplift"] = {"mean": float(r[promo].mean()) if promo.sum() > 50 else 0.0, "n": int(promo.sum())}
    return res


def dayparts(P: Panel, series) -> dict:
    full = (P.stock_hours[series, :CUTOFF + 1] == 0)[:, :, None]
    h = (P.hours[series, :CUTOFF + 1] * full).sum(1)  # (n, 24)
    grp = P.statics[series, 0]
    out = {}
    for g in np.unique(grp):
        prof = h[grp == g].sum(0)
        parts = np.array([prof[a:b].sum() for a, b in DAYPARTS])
        out[str(int(g))] = [round(float(x), 4) for x in parts / parts.sum()]
    return out


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--data-dir", default="/kaggle/working/frn_raw")
    ap.add_argument("--out", default="/kaggle/working/out")
    ap.add_argument("--hours", type=float, default=10.8, help="ngan sach gio (phien Kaggle toi da 12 gio)")
    ap.add_argument("--lr", type=float, default=0.03)
    args = ap.parse_args()
    budget = Budget(args.hours)
    out = Path(args.out)
    (out / "artifacts").mkdir(parents=True, exist_ok=True)
    (out / "frn").mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)

    df = load(Path(args.data_dir), args.smoke)
    log("nap", len(df), "dong")
    P = Panel(df)
    del df
    log(f"panel {P.n} chuoi x {P.T} ngay, {P.dates[0]} .. {P.dates[-1]}")

    stores = np.unique(P.store)
    others = np.array([s for s in stores if s != DEMO_STORE])
    held = np.concatenate([[DEMO_STORE], rng.choice(others, size=min(N_HELDOUT - 1, len(others) // 2), replace=False)])
    is_held = np.isin(P.store, held)
    train_s = np.where(~is_held)[0]
    held_s = np.where(is_held)[0]
    log(f"diem giu lai {len(held)} ({len(held_s)} chuoi), diem huan luyen {len(stores) - len(held)} ({len(train_s)} chuoi)")

    prof = hour_profiles(P)
    D, share = recover(P, prof)
    rec_check = recovery_check(P, prof, rng)
    log("kiem khoi phuc", rec_check)

    # Do co gian va tac dong khuyen mai: CHI DE BAO CAO. Ban v2 thu quy chuoi ve gia goc bang 1 + e x muc giam; e uoc
    # luong ra ~9,6 (khong hop ly - gia cua Dingdong co ve noi sinh: giam gia dung luc nhu cau cao) va lam moi phuong
    # phap du bao lech thap 14-31%. Nen KHONG quy doi: du bao nhu cau that dung nhu da xay ra, coi khuyen mai cua FRN la
    # bien dong OC khong biet truoc. LightGBM va EWMA thay cung mot lich su tho.
    el_train, el_held = elasticity(P, train_s), elasticity(P, held_s)
    log(f"co gian (chi bao cao) diem huan luyen e={el_train['all']['e']}, khuyen mai +{el_train['activity_uplift']['mean']:.0%}")
    e_hat = a_hat = 0.0
    P.sale_raw = P.sale
    D_raw = D
    P.fullprice = (P.discount >= 0.98) & (P.activity == 0)

    # Phan nhom de chot dung ML: muc ban (theo nguong cua tap huan luyen) x muc lat nhat
    lvl = P.sale[:, :CUTOFF + 1].mean(1)
    zero = (P.sale[:, :CUTOFF + 1] <= 0).mean(1)
    cuts = np.quantile(lvl[train_s], [1 / 3, 2 / 3])
    vol = np.where(lvl <= cuts[0], "ban_it", np.where(lvl <= cuts[1], "ban_vua", "ban_chay"))
    inter = np.where(zero > 0.3, "lat_nhat", "deu")
    segments = np.char.add(np.char.add(vol.astype(str), "|"), inter.astype(str))

    report = {"version": 3, "recovery_check": rec_check, "segment_cuts_frn_units": [float(c) for c in cuts],
              "elasticity": {"train_stores": el_train, "heldout_stores": el_held}}
    meta = {"version": 3, "features": list(FEATURES), "categorical": CATEGORICAL, "k_scale": K_SCALE, "window": WINDOW,
            "max_h": MAX_H, "dates": [P.dates[0].isoformat(), P.dates[-1].isoformat()], "cutoff_day": CUTOFF,
            "cutoff_date": P.dates[CUTOFF].isoformat(), "t0_day": T0, "t0_date": P.dates[T0].isoformat(),
            "demo_store": DEMO_STORE, "heldout_stores": [int(s) for s in held], "quantiles": list(QUANTILES),
            "segment_cuts_oc_units": [float(c * K_SCALE) for c in cuts], "intermittent_zero_share": 0.3,
            "deflate": {"elasticity": e_hat, "activity_uplift": a_hat}, "use_ml_segments": []}

    def save_json():
        report["log"] = LOG
        meta["runtime_s"] = round(budget.used())
        (out / "artifacts" / "meta.json").write_text(json.dumps(meta, indent=1))
        (out / "frn" / "report.json").write_text(json.dumps(report, indent=1, default=float))

    # Ghi phan du lieu (re, nhanh) TRUOC khi hoc: neu het gio van con du lieu cho OC
    (out / "frn" / "elasticity.json").write_text(json.dumps({"engine": el_train, "world": el_held}, indent=1))
    dp = {"engine": dayparts(P, train_s),
          "world_by_store": {str(int(s)): dayparts(P, np.where(P.store == s)[0]) for s in held}}
    (out / "frn" / "dayparts.json").write_text(json.dumps(dp, indent=1))
    rows = []
    for i in held_s:
        for j in range(P.T):
            rows.append((int(P.store[i]), int(P.product[i]), int(P.city[i]), int(P.statics[i, 0]),
                         int(P.statics[i, 1]), int(P.statics[i, 2]), int(P.cat3[i]), j, P.dates[j].isoformat(),
                         round(float(P.sale_raw[i, j]), 4), round(float(D[i, j]), 4), round(float(D_raw[i, j]), 4),
                         int(P.stock_hours[i, j]), round(float(P.discount[i, j]), 4), int(P.activity[i, j]),
                         int(P.holiday[j])))
    cols = ["store_id", "product_id", "city_id", "management_group_id", "first_category_id", "second_category_id",
            "third_category_id", "day", "dt", "sale", "demand", "demand_raw", "stock_hours", "discount", "activity",
            "holiday"]
    with gzip.open(out / "frn" / "stores_daily.csv.gz", "wt", encoding="utf-8") as f:
        pd.DataFrame(rows, columns=cols).to_csv(f, index=False)
    save_json()

    step = 3 if args.smoke else 1  # dung moi moc du bao: phien 12 gio du cho toan bo du lieu
    lr = 0.1 if args.smoke else args.lr
    ev_origins_bt = list(range(T0, P.T - 1, 3 if args.smoke else 1))

    # Du bao EWMA (dac trung + moc so sanh), tinh song song
    t0 = time.time()
    tr_origins = sorted(set(range(WINDOW - 1, CUTOFF, step)))
    ew_train = ewma_all(P, train_s, tr_origins)
    ew_held = ewma_all(P, held_s, sorted(set([CUTOFF] + ev_origins_bt)))
    ew_held_nos = ewma_all(P, held_s, sorted(set([CUTOFF] + ev_origins_bt)), use_stockout=False)
    log(f"du bao EWMA cho {len(tr_origins)} moc: {time.time() - t0:.0f}s")

    # --- mo hinh chay that (cat o ngay 90): do tham so, hoc, danh gia
    X, y, td = samples(P, D, share, train_s, tr_origins, CUTOFF, ew_train)
    log(f"mo hinh chay that: {len(y)} mau")
    params, search = search_params(X, y, td, CUTOFF - 6, args.smoke, budget, rng)
    report["param_search"] = search
    meta["params"] = {**params, "learning_rate": lr}
    log("tham so chon:", params)
    save_json()
    # Du tru: mo hinh backtest (~45% thoi gian mo hinh chay that) + danh gia + nen
    models, info = train_quantiles(X, y, td, CUTOFF - 6, args.smoke, "", out / "artifacts", params, lr, budget,
                                   reserve_s=0.45 * max(0.0, budget.left()) + 1800)
    meta["train_info"] = info
    save_json()

    def methods_for(models_, ew, ew_nos):
        return {"lightgbm": lambda s, t: predict(models_, P, s, t, ew),
                "ewma_oc": lambda s, t: ewma_pred(ew, t),
                "ewma_khong_co_het_hang": lambda s, t: ewma_pred(ew_nos, t),
                "cung_thu_tuan_truoc": lambda s, t: naive(P, s, t),
                "tb_28_ngay": lambda s, t: ma28(P, s, t)}

    ev = evaluate(P, D, share, held_s, [CUTOFF], methods_for(models, ew_held, ew_held_nos), segments)
    report["eval_week_heldout"] = ev
    imp = models[0.5].feature_importance("gain")
    report["importance_q50"] = {f: float(v) for f, v in sorted(zip(FEATURES, imp), key=lambda x: -x[1])}
    gate = {}
    for seg in sorted(set(segments.tolist())):
        a, b = ev["lightgbm"]["obs"].get(seg), ev["ewma_oc"]["obs"].get(seg)
        gate[seg] = bool(a and b and a["wape"] < b["wape"] and a["pinball50"] < b["pinball50"]
                         and a.get("coverage80", 0) >= b.get("coverage80", 0) - 0.05)
    meta["use_ml_segments"] = [s for s, v in gate.items() if v]
    meta["metrics_eval_week"] = {m: ev[m]["obs"]["all"] for m in ev}
    report["gate"] = gate
    log("nhom dung ML:", meta["use_ml_segments"])
    save_json()

    # --- mo hinh backtest (chi thay du lieu den ngay T0), cung tham so
    bt_origins = [t for t in tr_origins if t < T0]
    Xb, yb, tdb = samples(P, D, share, train_s, bt_origins, T0, ew_train)
    log(f"mo hinh backtest: {len(yb)} mau")
    bt_models, bt_info = train_quantiles(Xb, yb, tdb, T0 - 6, args.smoke, "bt_", out / "artifacts", params, lr, budget,
                                         reserve_s=2400)
    meta["train_info"].update(bt_info)
    del Xb, yb, tdb
    report["rolling_heldout_bt"] = evaluate(P, D, share, held_s, ev_origins_bt,
                                            methods_for(bt_models, ew_held, ew_held_nos), segments)
    log("danh gia cuon chieu xong")
    save_json()

    # --- con gio: hoc lai mo hinh chay that tren toan bo du lieu (ca 7 ngay gan nhat)
    if True:  # chay thu cung di qua buoc hoc lai (so vong nho)
        meta["refit_all"] = refit_all(X, y, "", out / "artifacts", params, lr, meta["train_info"], budget,
                                      reserve_s=900)
    save_json()
    log(f"xong trong {budget.used() / 60:.1f} phut")
    print(json.dumps(meta["metrics_eval_week"], indent=1))


if __name__ == "__main__":
    main()
