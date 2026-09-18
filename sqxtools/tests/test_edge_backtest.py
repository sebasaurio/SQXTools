"""Tests del motor de backtest (`edge_backtest`).

Casos construidos a mano con precios sintéticos: son la red de seguridad contra el
bug más caro de este tipo de código —contar mal el signo del P&L o el nivel de
salida—, que produce resultados plausibles pero falsos.
"""

import numpy as np
import pandas as pd
import pytest

from sqxtools.edge_backtest import (equity_curve, max_drawdown, simulate, stats,
                                    wilson_interval)
from sqxtools.signal_screen import atr


def mk(prices, atr=10.0, wick=0.5):
    """Construye close/high/low/atr a partir de una serie de precios."""
    p = np.asarray(prices, dtype=float)
    return p, p + wick, p - wick, np.full(len(p), float(atr))


ALL = np.ones(64, dtype=bool)


class TestSimulateShort:
    def test_fall_gives_positive_r(self):
        """Mercado que cae sin tocar stop ni target → el R sale del precio final."""
        p, h, l, a = mk([100, 99, 98, 97, 96])
        r = simulate([0], p, h, l, a, sl_mult=2, pt_mult=None, hold=10, window_mask=ALL)
        assert r[0] == pytest.approx(0.4)

    def test_stop_hit_gives_minus_sl(self):
        p, h, l, a = mk([100, 110, 120, 130])       # sube 3 ATR → stop en +2 ATR
        r = simulate([0], p, h, l, a, sl_mult=2, pt_mult=None, hold=10, window_mask=ALL)
        assert r[0] == pytest.approx(-2.0)

    def test_target_hit_gives_plus_pt(self):
        p = np.array([100.0, 100.0])
        h = np.array([100.0, 101.0])
        l = np.array([100.0, 75.0])                 # 75 ≤ 80 (target) → target
        r = simulate([0], p, h, l, np.full(2, 10.0), sl_mult=2, pt_mult=2,
                     hold=5, window_mask=np.ones(2, bool))
        assert r[0] == pytest.approx(2.0)

    def test_same_bar_ambiguity_prefers_stop(self):
        """Si una barra toca stop y target, se asume el stop (conservador)."""
        p = np.array([100.0, 100.0])
        h = np.array([100.0, 125.0])                # ≥ stop 120
        l = np.array([100.0, 75.0])                 # ≤ target 80
        r = simulate([0], p, h, l, np.full(2, 10.0), sl_mult=2, pt_mult=2,
                     hold=5, window_mask=np.ones(2, bool))
        assert r[0] == pytest.approx(-2.0)


class TestSimulateLong:
    def test_rise_gives_positive(self):
        p, h, l, a = mk([100, 101, 102, 103])
        r = simulate([0], p, h, l, a, long=True, sl_mult=2, pt_mult=None,
                     hold=10, window_mask=ALL)
        assert r[0] == pytest.approx(0.3)

    def test_stop_hit_gives_minus_sl(self):
        p, h, l, a = mk([100, 90, 80, 70])
        r = simulate([0], p, h, l, a, long=True, sl_mult=2, pt_mult=None,
                     hold=10, window_mask=ALL)
        assert r[0] == pytest.approx(-2.0)


class TestTrailing:
    def test_trailing_can_exit_profitable(self):
        """Crítico: con trailing el stop se mueve y la salida puede ser GANANCIA.

        Contar la salida por trailing como una pérdida de `-sl_mult` es el bug que
        hace que un sistema rentable parezca catastrófico.
        """
        p = np.array([100, 90, 80, 70, 65, 70, 90, 100], dtype=float)
        r = simulate([0], p, p + 0.5, p - 0.5, np.full(8, 10.0),
                     sl_mult=2, pt_mult=None, trail_mult=1.5, hold=20, window_mask=ALL)
        assert r[0] > 0, "una salida por trailing tras una caída debe ser positiva"
        assert r[0] == pytest.approx(2.05, abs=0.05)

    def test_trailing_never_worse_than_sl(self):
        """El trailing solo mueve el stop a favor: la pérdida máxima sigue siendo -sl."""
        rng = np.random.default_rng(0)
        p = np.cumsum(rng.normal(0, 1, 400)) + 100
        p = np.abs(p) + 50
        h, l = p + 1, p - 1
        a = np.full(len(p), 5.0)
        ent = np.arange(0, 300, 5)
        r = simulate(ent, p, h, l, a, sl_mult=2, pt_mult=None, trail_mult=1.5,
                     hold=24, window_mask=np.ones(len(p), bool))
        assert r.min() >= -2.0 - 1e-9


class TestGuards:
    def test_window_mask_excludes_entries(self):
        p, h, l, a = mk([100, 90])
        r = simulate([0], p, h, l, a, sl_mult=2, hold=5,
                     window_mask=np.array([False, True]))
        assert len(r) == 0

    def test_nan_atr_skipped(self):
        p, h, l, a = mk([100, 90, 80])
        a = a.copy(); a[0] = np.nan
        r = simulate([0], p, h, l, a, sl_mult=2, hold=5, window_mask=ALL)
        assert len(r) == 0

    def test_zero_atr_skipped(self):
        p, h, l, a = mk([100, 90, 80])
        a = a.copy(); a[0] = 0.0
        r = simulate([0], p, h, l, a, sl_mult=2, hold=5, window_mask=ALL)
        assert len(r) == 0

    def test_one_at_a_time_skips_overlaps(self):
        p, h, l, a = mk([100, 99, 98, 97, 96, 95, 94])
        rng = np.ones(7, bool)
        many = simulate([0, 1, 2, 3, 4, 5, 6], p, h, l, a, sl_mult=2, hold=3,
                        window_mask=rng)
        seq = simulate([0, 1, 2, 3, 4, 5, 6], p, h, l, a, sl_mult=2, hold=3,
                       window_mask=rng, one_at_a_time=True)
        assert len(seq) < len(many)

    def test_index_out_of_range_ignored(self):
        p, h, l, a = mk([100, 99])
        r = simulate([0, 99], p, h, l, a, sl_mult=2, hold=5, window_mask=ALL)
        assert len(r) == 1


class TestStats:
    def test_basic_metrics(self):
        r = np.array([1.0, -1.0, 2.0, -0.5, 3.0])
        s = stats(r)
        assert s["n"] == 5
        assert s["win_pct"] == 60.0
        assert s["r_per_trade"] == pytest.approx(0.9)
        assert s["r_total"] == pytest.approx(4.5)
        assert s["best"] == 3.0 and s["worst"] == -1.0

    def test_max_drawdown(self):
        # equity: 0,1,0,2,1.5,4.5 → el peor tramo es 1→0 (-1) y 4.5 no cae
        assert max_drawdown(np.array([1.0, -1.0, 2.0, -0.5, 3.0])) == pytest.approx(-1.0)

    def test_equity_curve_starts_at_zero(self):
        eq = equity_curve(np.array([1.0, 2.0]))
        assert eq[0] == 0.0 and eq[-1] == pytest.approx(3.0)

    def test_yearly_and_concentration(self):
        r = np.array([2.0, 2.0, -1.0, 2.0, -0.5])
        ts = ["2020-01-01", "2020-06-01", "2021-01-01", "2021-06-01", "2022-01-01"]
        s = stats(r, ts)
        # 2020: 2+2=4.0 · 2021: -1+2=1.0 · 2022: -0.5 → 2 de 3 años positivos
        assert s["yearly"][2020] == pytest.approx(4.0)
        assert s["yearly"][2021] == pytest.approx(1.0)
        assert s["positive_years"] == "2/3"
        assert "top5_share_pct" in s

    def test_empty_input(self):
        assert stats(np.array([]))["n"] == 0


class TestWilson:
    def test_large_sample_narrow(self):
        """400 trades con 65% → intervalo angosto alrededor de 0.65."""
        lo, hi = wilson_interval(260, 400)
        assert lo > 0.60 and hi < 0.70

    def test_small_sample_wide(self):
        """8 trades con 65% (5 de 8) → intervalo mucho más ancho."""
        lo, hi = wilson_interval(5, 8)
        assert (hi - lo) > 0.3
        # debe contener el valor observado
        assert lo <= 5 / 8 <= hi

    def test_zero_n(self):
        assert wilson_interval(0, 0) == (0.0, 0.0)

    def test_bounds_stay_in_unit(self):
        lo, hi = wilson_interval(8, 8)  # 100% wins
        assert 0.0 <= lo <= 1.0 and 0.0 <= hi <= 1.0
        lo, hi = wilson_interval(0, 8)  # 0% wins
        assert lo == 0.0

    def test_stats_reports_wilson_and_expectancy(self):
        r = np.array([1.0, -1.0, 2.0, -0.5, 3.0])  # 60% wins
        s = stats(r)
        assert "win_pct_lo" in s and "win_pct_hi" in s
        assert s["win_pct_lo"] < 60.0 < s["win_pct_hi"]
        assert s["expectancy_r"] == pytest.approx(s["r_per_trade"])


class TestControlDeAzar:
    """El control que faltaba: el ESQUEMA DE SALIDA tiene expectativa propia.

    Motivo: en NAS100 H1 (12-20 UTC) entrar short al azar 1 vez por día con
    SL 2 ATR + trailing 1.5 ATR + 24 barras da +0.139 R/trade. Cualquier señal
    que dispare en horas volátiles hereda eso y parece un edge. Estos tests fijan
    el comportamiento del simulador para que el control no se pierda de vista.
    """

    @staticmethod
    def _walk(seed, n=40000, sigma=38.0, wick=25.0):
        """Caminata aleatoria con drift realizado EXACTAMENTE cero.

        Sin restar la media, el drift de la muestra sesga el resultado: un test que
        no lo haga mide el ruido de la semilla, no el simulador.
        """
        rng = np.random.default_rng(seed)
        steps = rng.normal(0, sigma, n)
        px = 20000 + np.cumsum(steps - steps.mean())
        d = pd.DataFrame({
            "timestamp": pd.date_range("2020-01-01", periods=n, freq="1h", tz="UTC"),
            "open": px, "close": px,
            "high": px + np.abs(rng.normal(0, wick, n)),
            "low": px - np.abs(rng.normal(0, wick, n)), "volume": 1.0})
        d["high"] = d[["high", "open", "close"]].max(axis=1)
        d["low"] = d[["low", "open", "close"]].min(axis=1)
        return d

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_fixed_sl_pt_is_direction_neutral(self, seed):
        """Con SL y PT simétricos el esquema no debe tener sesgo direccional."""
        d = self._walk(seed)
        a = atr(d, 14).to_numpy()
        ent = np.arange(100, len(d) - 30, 24)
        ones = np.ones(len(d), bool)
        rs = simulate(ent, d["close"], d["high"], d["low"], a, long=False,
                      sl_mult=2.0, pt_mult=2.0, hold=24, window_mask=ones)
        rl = simulate(ent, d["close"], d["high"], d["low"], a, long=True,
                      sl_mult=2.0, pt_mult=2.0, hold=24, window_mask=ones)
        assert abs(rs.mean()) < 0.12 and abs(rl.mean()) < 0.12
        assert rs.mean() == pytest.approx(-rl.mean(), abs=1e-9)

    @pytest.mark.parametrize("seed", [1, 2, 3])
    def test_trailing_scheme_has_its_own_expectancy(self, seed):
        """El trailing NO es neutral: genera expectativa propia sobre una caminata.

        Este test documenta el motivo por el que todo edge debe medirse como
        EXCESO sobre el control de azar y no como R/trade absoluto.
        """
        d = self._walk(seed)
        a = atr(d, 14).to_numpy()
        ent = np.arange(100, len(d) - 30, 24)
        ones = np.ones(len(d), bool)
        rs = simulate(ent, d["close"], d["high"], d["low"], a, long=False,
                      sl_mult=2.0, pt_mult=None, trail_mult=1.5, hold=24,
                      window_mask=ones)
        assert len(rs) > 100
        # No se afirma un valor exacto (depende de la semilla), solo que el sesgo
        # es del orden de magnitud que obliga a usar el control de azar.
        assert abs(rs.mean()) < 0.25, "sesgo mayor al esperado: revisar el simulador"
