"""Demand forecasting: code, never the LLM.

Models
  lightgbm        global direct multi-horizon gradient-boosting model (primary)
  ets             Holt-Winters additive weekly seasonality (statsmodels), per SKU
  seasonal_ses    weekly seasonal profile x simple exponential smoothing (fast fallback)
  seasonal_naive  value from the same weekday last week
  naive           last observed value

Metrics: WAPE = sum|a-f| / sum a ; MAPE = mean |a-f|/a over days with a > 0.
"""
from __future__ import annotations

import math
import random
import statistics
import threading
import warnings
from typing import Optional

import numpy as np

H = 28  # maximum forecast horizon (days)


# ------------------------------------------------------------------ metrics
def wape(actual: list, fc: list) -> float:
    tot = sum(actual)
    return sum(abs(a - f) for a, f in zip(actual, fc)) / tot if tot else 0.0


def mape(actual: list, fc: list) -> float:
    terms = [abs(a - f) / a for a, f in zip(actual, fc) if a > 0]
    return statistics.mean(terms) if terms else 0.0


# ------------------------------------------------------------------ simple baselines
def naive(hist: dict, as_of: int, h: int = H) -> list:
    last = next((hist[d] for d in range(as_of - 1, as_of - 15, -1) if d in hist), 0)
    return [float(last)] * h


def seasonal_naive(hist: dict, as_of: int, h: int = H) -> list:
    return [float(hist.get(as_of - 7 + (i % 7), 0)) for i in range(h)]


def seasonal_ses(hist: dict, as_of: int, h: int = H) -> tuple[list, float]:
    """Weekly seasonal profile x exponentially smoothed level. Returns (daily, sigma)."""
    days = sorted(d for d in hist if d < as_of)
    vals = [hist[d] for d in days]
    overall = statistics.mean(vals) if vals else 0.0
    overall = overall or 1e-9
    dow = {i: [] for i in range(7)}
    for d in days:
        dow[d % 7].append(hist[d])
    factor = {i: (statistics.mean(v) / overall if len(v) >= 3 else 1.0) for i, v in dow.items()}
    level, resid = None, []
    for d in days:
        deseason = hist[d] / max(factor[d % 7], 0.2)
        if level is not None:
            resid.append(hist[d] - level * factor[d % 7])
        level = deseason if level is None else 0.2 * deseason + 0.8 * level
    level = level or 0.0
    sigma = statistics.pstdev(resid[-28:]) if len(resid) >= 5 else (math.sqrt(overall) if overall > 0 else 0.0)
    return [max(0.0, level * factor[(as_of + i) % 7]) for i in range(h)], sigma


def ets(hist: dict, as_of: int, h: int = H) -> list:
    """Holt-Winters (additive weekly seasonality). Falls back to seasonal_ses on failure."""
    days = [d for d in hist if d < as_of]
    if len(days) < 21:
        return seasonal_ses(hist, as_of, h)[0]
    start = min(days)
    series, last = [], None
    for d in range(start, as_of):  # forward-fill missing days
        last = hist.get(d, last if last is not None else 0)
        series.append(float(last))
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            fit = ExponentialSmoothing(series, trend=None, seasonal="add", seasonal_periods=7,
                                       initialization_method="estimated").fit()
            # the series ends at as_of-1, so step i of the forecast is day as_of+i
            return [max(0.0, float(x)) for x in fit.forecast(h)]
    except Exception:
        return seasonal_ses(hist, as_of, h)[0]


# ------------------------------------------------------------------ LightGBM global model
FEATURES = ["k", "dow", "doy_sin", "doy_cos", "promo", "promo_rate28", "m7_r", "dow_r", "std28_r", "last_r",
            "log_m28", "log_n"]


def _arrays(hist: dict, promos: set, upto: int):
    """Dense arrays (NaN = missing day) for days 0..upto-1."""
    a = np.full(upto, np.nan)
    for d, q in hist.items():
        if 0 <= d < upto:
            a[d] = q
    p = np.zeros(upto + H + 1)
    for d in promos:
        if 0 <= d < len(p):
            p[d] = 1.0
    return a, p


def _origin_rows(a: np.ndarray, p: np.ndarray, t: int, ks) -> Optional[tuple[np.ndarray, float]]:
    """Feature rows at origin t (only data strictly before t) for targets t+k-1, k in ks."""
    w28 = a[max(0, t - 28):t]
    w28 = w28[~np.isnan(w28)]
    if len(w28) < 7:
        return None
    m28 = float(w28.mean()) + 0.5
    w7 = a[max(0, t - 7):t]
    w7 = w7[~np.isnan(w7)]
    m7 = float(w7.mean()) if len(w7) else m28
    hist8 = a[max(0, t - 56):t]
    last_idx = np.where(~np.isnan(a[max(0, t - 7):t]))[0]
    last = float(a[max(0, t - 7) + last_idx[-1]]) if len(last_idx) else float(w28[-1])
    n = float(np.count_nonzero(~np.isnan(a[:t])))
    base = [float(p[max(0, t - 28):t].mean()), m7 / m28, float(w28.std()) / m28, last / m28,
            math.log(m28), math.log1p(n)]
    off = max(0, t - 56)
    dow_mean = {}
    for r in range(7):
        v = hist8[[i for i in range(len(hist8)) if (off + i) % 7 == r]]
        v = v[~np.isnan(v)]
        dow_mean[r] = float(v.mean()) / m28 if len(v) else 1.0
    rows = []
    for k in ks:
        target = t + k - 1
        rows.append([k, target % 7, math.sin(2 * math.pi * target / 365), math.cos(2 * math.pi * target / 365),
                     float(p[target]) if target < len(p) else 0.0, base[0], base[1], dow_mean[target % 7],
                     base[2], base[3], base[4], base[5]])
    return np.asarray(rows, dtype=float), m28


class LGBMForecaster:
    """One model for all SKUs. Target is demand scaled by the trailing 28-day mean, so one
    model serves fast and slow movers. Trained only on data before `as_of`."""

    def __init__(self, histories: dict, promos: dict, as_of: int, max_train_skus: int = 200, seed: int = 0):
        import lightgbm as lgb  # heavy dependency, imported lazily
        self.as_of = as_of
        skus = sorted(histories)
        if len(skus) > max_train_skus:
            skus = sorted(random.Random(seed).sample(skus, max_train_skus))
        X, y, owner, scales, actuals = [], [], [], [], []
        for sku in skus:
            a, p = _arrays(histories[sku], promos.get(sku, set()), as_of)
            for t in range(max(28, as_of - 7 * 20), as_of, 7):
                ks = [k for k in range(1, H + 1) if t + k - 1 < as_of and not np.isnan(a[t + k - 1])]
                if not ks:
                    continue
                res = _origin_rows(a, p, t, ks)
                if res is None:
                    continue
                rows, m28 = res
                tgt = np.array([a[t + k - 1] for k in ks])
                X.append(rows)
                y.append(np.minimum(6.0, tgt / m28))
                owner += [sku] * len(ks)
                scales.append(np.full(len(ks), m28))
                actuals.append(tgt)
        if not X or sum(len(x) for x in X) < 200:
            raise ValueError("not enough history to train LightGBM")
        X, y = np.vstack(X), np.concatenate(y)
        params = {"objective": "regression", "learning_rate": 0.05, "num_leaves": 15, "min_data_in_leaf": 20,
                  "bagging_fraction": 0.8, "bagging_freq": 1, "feature_fraction": 0.9, "seed": seed,
                  "deterministic": True, "num_threads": 1, "verbose": -1}
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            self.model = lgb.train(params, lgb.Dataset(X, label=y, feature_name=FEATURES), num_boost_round=150)
            pred = self.model.predict(X)
        resid = np.concatenate(actuals) - pred * np.concatenate(scales)
        per: dict = {}
        for sku, r in zip(owner, resid):
            per.setdefault(sku, []).append(float(r))
        self.resid_sigma = {s: float(np.std(v)) for s, v in per.items() if len(v) >= 5}
        self.n_train = len(X)

    def predict(self, hist: dict, promos: set, h: int = H) -> Optional[tuple[list, None]]:
        a, p = _arrays(hist, promos, self.as_of)
        res = _origin_rows(a, p, self.as_of, range(1, h + 1))
        if res is None:
            return None
        rows, m28 = res
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            out = self.model.predict(rows)
        return [max(0.0, float(v) * m28) for v in out], None


_cache: dict = {}
_cache_lock = threading.Lock()


def get_lgbm(key, histories_fn, promos_fn, as_of: int) -> Optional[LGBMForecaster]:
    """Train once per (database, as_of) and reuse; returns None if LightGBM is unavailable."""
    with _cache_lock:
        if key in _cache:
            return _cache[key]
        try:
            m = LGBMForecaster(histories_fn(), promos_fn(), as_of)
        except Exception:
            m = None
        if len(_cache) > 64:
            _cache.clear()
        _cache[key] = m
        return m
