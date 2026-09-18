"""Tests del Monte Carlo analysis (`monte_carlo`).

Verifican la lógica estadística con series sintéticas: la distribución de
equity paths, la tasa de ruina, el profit rate y los percentiles de drawdown.
La clave de robustez es que los resultados deben ser reproducibles con semilla
y responder a señales obvias (una serie perdedora debe tener profit_rate ≈ 0).
"""

import numpy as np
import pytest

from sqxtools.monte_carlo import (analyze, equity_paths, format_report,
                                  max_drawdown_series)


class TestEquityPaths:
    def test_shape(self):
        r = np.array([1.0, -1.0, 0.5, -0.5])
        paths = equity_paths(r, n_runs=50, seed=1)
        assert paths.shape == (50, 5)  # len(r)+1 columnas (col 0 = 0.0)

    def test_starts_at_zero(self):
        paths = equity_paths(np.array([1.0, 2.0]), n_runs=10, seed=0)
        assert np.all(paths[:, 0] == 0.0)

    def test_nan_and_inf_dropped(self):
        r = np.array([1.0, np.nan, np.inf, 2.0, -1.0])
        paths = equity_paths(r, n_runs=10, seed=0)
        # solo 3 trades válidos → 4 columnas
        assert paths.shape[1] == 4

    def test_empty(self):
        paths = equity_paths(np.array([]), n_runs=5)
        assert paths.shape == (5, 1)

    def test_reproducible_with_seed(self):
        r = np.array([1.0, -0.5, 2.0, -1.0, 0.5, -0.2, 1.5])
        a = equity_paths(r, n_runs=100, seed=42)
        b = equity_paths(r, n_runs=100, seed=42)
        assert np.array_equal(a, b)


class TestMaxDrawdownSeries:
    def test_single_trade_loss(self):
        # equity: 0 → -1 (pierde 1)
        dd = max_drawdown_series(np.array([[0.0, -1.0]]))
        assert dd[0] == pytest.approx(-1.0)

    def test_peak_then_drop(self):
        eq = np.array([[0.0, 3.0, 3.0, 1.0]])  # peak 3 → baja a 1 → dd -2
        dd = max_drawdown_series(eq)
        assert dd[0] == pytest.approx(-2.0)


class TestAnalyze:
    def test_losing_series_rarely_profitable(self):
        r = np.array([-1.0] * 50 + [0.2, -0.8])  # mayormente perdedor
        res = analyze(r, n_runs=500, seed=7)
        assert res["profit_rate"] < 30.0

    def test_winning_series_mostly_profitable(self):
        r = np.array([1.0, 1.5, -0.5] * 40)  # expectativa claramente positiva
        res = analyze(r, n_runs=500, seed=7)
        assert res["profit_rate"] > 70.0

    def test_ruin_level(self):
        # Serie que ocasionalmente encadena -1 varias veces → con ruin en -5
        # alguna simulación debe tocarlo.
        r = np.array([-1.0, -1.0, -1.0, -1.0, -1.0, 3.0] * 30)
        res = analyze(r, n_runs=2000, seed=3, ruin_level=-5.0)
        assert "bust_rate" in res
        assert res["bust_rate"] > 0.0

    def test_empty(self):
        res = analyze(np.array([]), n_runs=10)
        assert res["n_trades"] == 0 and res["profit_rate"] is None

    def test_max_dd_negative(self):
        res = analyze(np.array([1.0, -2.0, 1.0, -1.0, 2.0]), n_runs=200, seed=1)
        assert res["max_dd"]["worst"] < 0.0

    def test_band_present(self):
        res = analyze(np.array([1.0, -0.5, 1.5, -1.0, 0.5]), n_runs=100, seed=2)
        b = res["band"]
        assert b["final_lo"] <= b["final_mean"] <= b["final_hi"]


class TestFormatReport:
    def test_renders(self):
        res = analyze(np.array([1.0, -0.5, 2.0, -1.0]), n_runs=50, seed=1,
                      ruin_level=-3.0)
        txt = format_report(res)
        assert "Monte Carlo" in txt
        assert "profit_rate" in txt or "Rentable" in txt
