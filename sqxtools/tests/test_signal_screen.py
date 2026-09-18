"""Tests del screener de señales (`signal_screen`).

Usa datos sintéticos con semilla fija: el objetivo es validar la estadística y la
estructura, no el resultado de mercado (que depende de los datos reales).
"""

import numpy as np
import pandas as pd
import pytest

from sqxtools.signal_screen import (
    atr,
    bollinger,
    build_conditions,
    evaluate_signal,
    nw_tstat,
    rsi,
    screen,
    supertrend,
)


def make_df(n: int = 4000, seed: int = 0, drift: float = 0.0001,
            vol: float = 0.005) -> pd.DataFrame:
    """OHLCV sintético consistente (high ≥ max(open, close), low ≤ min(...))."""
    rng = np.random.default_rng(seed)
    close = 10000 * np.exp(np.cumsum(rng.normal(drift, vol, n)))
    open_ = np.concatenate([[close[0]], close[:-1]])
    wig_u = np.abs(rng.normal(0, 0.001, n))
    wig_d = np.abs(rng.normal(0, 0.001, n))
    high = np.maximum.reduce([close * (1 + wig_u), open_, close])
    low = np.minimum.reduce([close * (1 - wig_d), open_, close])
    return pd.DataFrame({
        "timestamp": pd.date_range("2020-01-01", periods=n, freq="h", tz="UTC"),
        "open": open_, "high": high, "low": low, "close": close,
        "volume": np.abs(rng.normal(1.0, 0.3, n)),
    })


class TestNeweyWest:
    def test_iid_close_to_naive(self):
        """Sin autocorrelación, NW ≈ t clásico.

        No son idénticos: NW usa el momento poblacional (1/n) y el t clásico la
        varianza muestral (ddof=1). La diferencia es el factor n/(n-1) → ~2e-4 para
        n=5000. Se compara con tolerancia relativa amplia por eso.
        """
        rng = np.random.default_rng(7)
        x = rng.normal(0.001, 0.01, 5000)
        t_nw = nw_tstat(x, lag=0)
        t_naive = x.mean() / (x.std(ddof=1) / np.sqrt(len(x)))
        assert t_nw == pytest.approx(t_naive, rel=1e-3)

    def test_overlap_is_penalized(self):
        """Con retornos solapados el t-stat debe BAJAR (si no, todo parece significativo)."""
        rng = np.random.default_rng(3)
        shocks = rng.normal(0, 1, 8000)
        fwd = pd.Series(shocks).rolling(8).mean().dropna().to_numpy()
        t_nw = nw_tstat(fwd, lag=7)
        t_naive = fwd.mean() / (fwd.std(ddof=1) / np.sqrt(len(fwd)))
        assert abs(t_nw) < abs(t_naive)

    def test_constant_series_is_safe(self):
        assert nw_tstat(np.zeros(100), lag=5) == 0.0


class TestIndicators:
    def test_rsi_bounds(self):
        df = make_df()
        r = rsi(df["close"]).dropna()
        assert r.between(0, 100).all()

    def test_atr_positive(self):
        df = make_df()
        a = atr(df).dropna()
        assert (a > 0).all()

    def test_bollinger_ordering(self):
        df = make_df()
        ma, up, lo = bollinger(df["close"])
        mask = ma.notna()
        assert (up[mask] >= ma[mask]).all() and (lo[mask] <= ma[mask]).all()

    def test_supertrend_binary(self):
        df = make_df()
        st = supertrend(df).dropna().unique()
        assert set(np.unique(st)).issubset({-1, 1})


class TestConditionsCatalog:
    def test_families_present(self):
        df = make_df(600)
        cats = build_conditions(df)
        for fam in ("tendencia", "fuerza", "momentum", "volatilidad", "volumen",
                    "vwap", "velas", "extension", "canales"):
            assert fam in cats, f"falta la familia {fam}"

    def test_conditions_are_boolean_series(self):
        df = make_df(600)
        for fam, group in build_conditions(df).items():
            for name, cond in group.items():
                assert isinstance(cond, pd.Series), f"{fam}/{name} no es Series"
                assert cond.dtype == bool, f"{fam}/{name} no es booleana"
                assert len(cond) == len(df)


class TestEvaluateSignal:
    def test_detects_planted_negative_edge(self):
        """Una condición con retorno forward negativo y poco ruido debe detectarse."""
        rng = np.random.default_rng(11)
        n = 3000
        vals = np.full(n, 0.0005)
        idx = np.arange(0, n, 6)
        vals[idx] = -0.004 + rng.normal(0, 0.0005, len(idx))
        fwd = pd.Series(vals)
        cond = pd.Series(False, index=range(n))
        cond.iloc[idx] = True

        res = evaluate_signal(cond, fwd, horizon=8, min_n=50)
        assert res is not None
        assert res["mean_fwd_pct"] < 0
        assert res["p_value"] < 0.01

    def test_returns_none_when_sample_too_small(self):
        fwd = pd.Series(np.random.default_rng(0).normal(0, 0.01, 200))
        cond = pd.Series(False, index=range(200))
        cond.iloc[:10] = True
        assert evaluate_signal(cond, fwd, horizon=4, min_n=50) is None

    def test_ignores_nan_forward(self):
        n = 500
        fwd = pd.Series([np.nan] * 450 + [0.01] * 50)
        cond = pd.Series(True, index=range(n))
        res = evaluate_signal(cond, fwd, horizon=4, min_n=40)
        assert res is not None and res["n"] == 50


class TestScreen:
    def test_structure(self):
        df = make_df(3000)
        res = screen(df, horizons=(4, 8), min_n=30)
        assert set(res) >= {"data_info", "config", "baseline", "resultados",
                            "destacados", "notas"}
        assert res["config"]["window"] == [12, 20]
        assert res["config"]["direction"] == "short"
        assert res["data_info"]["barras"] == 3000
        assert res["resultados"], "no se evaluó ninguna señal"
        r0 = res["resultados"][0]
        for key in ("familia", "senal", "horizonte", "n", "mean_fwd_pct", "edge_pct",
                    "p_value", "significativa", "favorable", "is_mean_pct", "oos_mean_pct"):
            assert key in r0
        for h in (4, 8):
            assert f"h{h}" in res["baseline"]

    def test_edge_sign_follows_direction(self):
        """El 'edge' debe invertirse al pedir la dirección opuesta."""
        df = make_df(3000)
        short = screen(df, horizons=(8,), min_n=30, direction="short")
        long_ = screen(df, horizons=(8,), min_n=30, direction="long")
        s = {(r["senal"], r["horizonte"]): r["edge_pct"] for r in short["resultados"]}
        l = {(r["senal"], r["horizonte"]): r["edge_pct"] for r in long_["resultados"]}
        for k in s:
            assert s[k] == pytest.approx(-l[k])

    def test_rejects_bad_direction(self):
        with pytest.raises(ValueError, match="direction"):
            screen(make_df(500), direction="lateral")

    def test_rejects_bad_split(self):
        with pytest.raises(ValueError, match="split"):
            screen(make_df(500), split=0.99)

    def test_window_restricts_entries(self):
        """Una ventana de una sola hora debe reducir drásticamente la muestra."""
        df = make_df(3000)
        wide = screen(df, window_from=0, window_to=23, horizons=(4,), min_n=30)
        narrow = screen(df, window_from=3, window_to=3, horizons=(4,), min_n=30)
        n_wide = max(r["n"] for r in wide["resultados"])
        n_narrow = max(r["n"] for r in narrow["resultados"])
        assert n_narrow < n_wide / 5

    def test_min_n_filters_results(self):
        df = make_df(1500)
        loose = screen(df, horizons=(4,), min_n=25)
        tight = screen(df, horizons=(4,), min_n=100000)
        assert tight["resultados"] == []
        assert loose["resultados"]
