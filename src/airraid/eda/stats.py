"""The 5 authoritative baseline analytical tools (plans/07 §3).

Each reads the read-only export, computes EXACT numbers with statsmodels/pandas, and returns an
`Analysis` whose plot carries those numbers inside the image. The MCP server and the LangGraph agent
wrap these — they do not re-implement statistics.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from statsmodels.tsa.seasonal import seasonal_decompose  # noqa: E402
from statsmodels.tsa.stattools import acf, adfuller, kpss, pacf  # noqa: E402

from . import data  # noqa: E402
from .data import ALERT_COLUMN  # noqa: E402  (re-exported)
from .plots import finalize, metrics_textbox  # noqa: E402

__all__ = ["ALERT_COLUMN", "analyze_seasonality", "plot_acf_pacf", "test_stationarity",
           "get_summary_statistics", "analyze_distribution"]


# --------------------------------------------------------------------------- 1. seasonality
def analyze_seasonality(oblast=None, column: str = ALERT_COLUMN, period: int = 24) -> "data.Analysis":
    s = data.hourly_series(column, oblast)
    _, name = data.resolve_oblast(oblast)
    if s.size < 2 * period:
        raise ValueError(f"need >= {2*period} hourly points, got {s.size}")

    res = seasonal_decompose(s, model="additive", period=period)
    resid = res.resid.dropna()
    seas = res.seasonal.loc[resid.index]
    denom = float((seas + resid).var())
    strength = max(0.0, 1.0 - float(resid.var()) / denom) if denom > 0 else 0.0
    by_hour = s.groupby(s.index.hour).mean()

    test_result = {
        "peak_hour": int(by_hour.idxmax()), "peak_value": round(float(by_hour.max()), 4),
        "trough_hour": int(by_hour.idxmin()), "trough_value": round(float(by_hour.min()), 4),
        "seasonal_strength": round(strength, 4), "period_hours": period, "n": int(s.size),
    }

    fig, axes = plt.subplots(2, 1, figsize=(12, 7))
    axes[0].plot(s.index, res.trend, color="navy", lw=0.9)
    axes[0].set_title(f"Trend — {name} · {column}")
    axes[0].set_ylabel("trend")
    axes[1].bar(by_hour.index, by_hour.values, color="steelblue")
    axes[1].set_xlabel("hour of day (UTC)")
    axes[1].set_ylabel("mean")
    axes[1].set_title("Hour-of-day profile (seasonal)")
    metrics_textbox(axes[1], test_result)
    fig.suptitle(f"Seasonality — {name} · {column}  (peak_hour={test_result['peak_hour']}, "
                 f"strength={test_result['seasonal_strength']})", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return finalize(fig, test_result, "seasonality", tool="analyze_seasonality",
                    oblast=name, column=column)


# --------------------------------------------------------------------------- 2. ACF / PACF
def plot_acf_pacf(oblast=None, column: str = ALERT_COLUMN, nlags: int = 48) -> "data.Analysis":
    s = data.hourly_series(column, oblast)
    _, name = data.resolve_oblast(oblast)
    nlags = int(min(nlags, max(1, s.size // 2 - 1)))
    a = acf(s.values, nlags=nlags, fft=True)
    p = pacf(s.values, nlags=nlags)
    conf = 1.96 / np.sqrt(s.size)
    sig = [int(i) for i in range(1, nlags + 1) if abs(a[i]) > conf]

    test_result = {
        "conf_threshold": round(float(conf), 4), "n_sig_acf_lags": len(sig),
        "top_acf_lags": sig[:10], "acf_lag1": round(float(a[1]), 4),
        "pacf_lag1": round(float(p[1]), 4), "nlags": nlags, "n": int(s.size),
    }

    fig, axes = plt.subplots(2, 1, figsize=(12, 7))
    for ax, vals, lab in ((axes[0], a, "ACF"), (axes[1], p, "PACF")):
        ax.stem(range(len(vals)), vals)
        ax.axhline(conf, ls="--", color="crimson", lw=0.8)
        ax.axhline(-conf, ls="--", color="crimson", lw=0.8)
        ax.set_ylabel(lab)
    axes[1].set_xlabel("lag (hours)")
    metrics_textbox(axes[0], test_result)
    fig.suptitle(f"ACF / PACF — {name} · {column}  ({test_result['n_sig_acf_lags']} sig lags, "
                 f"acf_lag1={test_result['acf_lag1']})", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    return finalize(fig, test_result, "acf_pacf", tool="plot_acf_pacf", oblast=name, column=column)


# --------------------------------------------------------------------------- 3. stationarity
def test_stationarity(oblast=None, column: str = ALERT_COLUMN) -> "data.Analysis":
    s = data.hourly_series(column, oblast)
    _, name = data.resolve_oblast(oblast)
    adf = adfuller(s.values, maxlag=24, autolag="AIC")
    adf_stat, adf_p, adf_crit = float(adf[0]), float(adf[1]), adf[4]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")  # KPSS interpolation warning when stat is out of table
        kpss_stat, kpss_p, _, kpss_crit = kpss(s.values, regression="c", nlags="auto")
    stationary = bool(adf_p < 0.05 and kpss_p > 0.05)

    test_result = {
        "adf_stat": round(adf_stat, 4), "adf_pvalue": round(adf_p, 4),
        "adf_crit_5pct": round(float(adf_crit["5%"]), 4),
        "kpss_stat": round(float(kpss_stat), 4), "kpss_pvalue": round(float(kpss_p), 4),
        "is_stationary": stationary, "n": int(s.size),
    }

    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(s.index, s.values, color="navy", lw=0.5)
    ax.set_ylabel(column)
    ax.set_title(f"Stationarity — {name} · {column}  "
                 f"(ADF p={test_result['adf_pvalue']}, KPSS p={test_result['kpss_pvalue']}, "
                 f"stationary={stationary})", fontsize=12)
    metrics_textbox(ax, test_result)
    fig.tight_layout()
    return finalize(fig, test_result, "stationarity", tool="test_stationarity",
                    oblast=name, column=column)


# --------------------------------------------------------------------------- 4. summary stats
def get_summary_statistics(oblast=None, column: str = "temp_c",
                           start: str | None = None, end: str | None = None) -> "data.Analysis":
    s = data.series(column, oblast).dropna()
    _, name = data.resolve_oblast(oblast)
    if start:
        s = s[s.index >= pd.Timestamp(start, tz="UTC")]
    if end:
        s = s[s.index < pd.Timestamp(end, tz="UTC")]
    if s.empty:
        raise ValueError("no data in the requested window")

    q = s.quantile([0.25, 0.5, 0.75])
    test_result = {
        "mean": round(float(s.mean()), 4), "median": round(float(s.median()), 4),
        "std": round(float(s.std()), 4), "variance": round(float(s.var()), 4),
        "min": round(float(s.min()), 4), "p25": round(float(q.loc[0.25]), 4),
        "p75": round(float(q.loc[0.75]), 4), "max": round(float(s.max()), 4), "n": int(s.size),
    }

    fig, ax = plt.subplots(figsize=(11, 5))
    ax.hist(s.values, bins=40, color="steelblue", edgecolor="white")
    ax.axvline(test_result["mean"], color="crimson", ls="--", lw=1.2, label="mean")
    ax.axvline(test_result["median"], color="green", ls=":", lw=1.2, label="median")
    ax.set_xlabel(column)
    ax.set_ylabel("count")
    ax.legend()
    ax.set_title(f"Summary statistics — {name} · {column}  "
                 f"(mean={test_result['mean']}, std={test_result['std']})", fontsize=12)
    metrics_textbox(ax, test_result, loc="upper right")
    fig.tight_layout()
    return finalize(fig, test_result, "summary", tool="get_summary_statistics",
                    oblast=name, column=column)


# --------------------------------------------------------------------------- 5. distribution
def analyze_distribution(oblast=None, column: str = "wind_speed") -> "data.Analysis":
    """Histogram/KDE + additive-vs-multiplicative regime check (variance-scales-with-level) +
    mean drift across the series (plans/07 §3, the §0 'multiplicative/additive changes' problem)."""
    s = data.series(column, oblast).dropna()
    _, name = data.resolve_oblast(oblast)
    if s.size < 24:
        raise ValueError("not enough data to characterize a distribution")

    half = s.size // 2
    m1, m2 = float(s.iloc[:half].mean()), float(s.iloc[half:].mean())
    # multiplicative ⇔ spread grows with level: correlate per-month mean vs std
    by_m = s.groupby(s.index.tz_localize(None).to_period("M"))
    mu, sd = by_m.mean(), by_m.std()
    ok = mu.notna() & sd.notna()
    corr = float(np.corrcoef(mu[ok].values, sd[ok].values)[0, 1]) if ok.sum() > 2 else float("nan")
    regime = "multiplicative" if (corr == corr and corr > 0.4) else "additive"

    test_result = {
        "mean": round(float(s.mean()), 4), "std": round(float(s.std()), 4),
        "skew": round(float(s.skew()), 4), "mean_first_half": round(m1, 4),
        "mean_second_half": round(m2, 4), "mean_drift": round(m2 - m1, 4),
        "level_spread_corr": (round(corr, 4) if corr == corr else None),
        "regime": regime, "n": int(s.size),
    }

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))
    axes[0].hist(s.values, bins=40, color="steelblue", edgecolor="white")
    axes[0].set_title(f"Raw distribution — {column}")
    axes[0].set_xlabel(column)
    logv = np.log1p(s.clip(lower=0).values)
    axes[1].hist(logv, bins=40, color="seagreen", edgecolor="white")
    axes[1].set_title("log1p distribution (variance-stabilized)")
    axes[1].set_xlabel(f"log1p({column})")
    metrics_textbox(axes[0], test_result)
    fig.suptitle(f"Distribution — {name} · {column}  (regime={regime}, "
                 f"drift={test_result['mean_drift']}, skew={test_result['skew']})", fontsize=13)
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    return finalize(fig, test_result, "distribution", tool="analyze_distribution",
                    oblast=name, column=column)
