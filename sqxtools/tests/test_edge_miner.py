"""Tests del minero de edges.

El test central es `test_no_lookahead`: es la red de seguridad contra el error más
peligroso de este módulo. Si un nivel se calcula con datos posteriores a la barra
donde se usa, los resultados salen espectaculares y completamente falsos (pasó:
el máximo del rango de apertura era visible a las 08:00 y daba +0.57 R/trade).

El test trunca el DataFrame y verifica que el valor de un nivel en la última barra
disponible NO cambie al agregar datos futuros. Si cambia, hay lookahead.
"""

import numpy as np
import pandas as pd
import pytest

from sqxtools.edge_miner import (LEVELS_MIN_HOUR, _prep, build_levels,
                                 entries_for, hourly_profile, scan_windows,
                                 triggers)

RNG = np.random.default_rng(7)


def synth(n_days: int = 90, start: str = "2025-01-01") -> pd.DataFrame:
    """Serie H1 sintética con caminata aleatoria, cubriendo 24h por día."""
    ts = pd.date_range(start, periods=n_days * 24, freq="1h", tz="UTC")
    close = 20000 + np.cumsum(RNG.normal(0, 12, len(ts)))
    high = close + np.abs(RNG.normal(0, 8, len(ts)))
    low = close - np.abs(RNG.normal(0, 8, len(ts)))
    return pd.DataFrame({
        "timestamp": ts, "open": close, "high": high, "low": low,
        "close": close, "volume": RNG.uniform(100, 500, len(ts)),
    })


class TestNoLookahead:
    @pytest.mark.parametrize("cut", [300, 700, 1500])
    def test_level_value_unchanged_by_future_data(self, cut):
        """Un nivel en la barra `cut-1` debe ser idéntico con o sin datos posteriores."""
        df = synth()
        full = build_levels(df)
        part = build_levels(df.iloc[:cut].reset_index(drop=True))
        for name in full:
            a, b = full[name][cut - 1], part[name][cut - 1]
            if np.isnan(a) or np.isnan(b):
                assert np.isnan(a) and np.isnan(b), f"{name}: NaN solo en un lado"
            else:
                assert a == pytest.approx(b, rel=1e-9), f"{name}: cambia con datos futuros"

    def test_session_levels_not_available_before_formation(self):
        """El rango de apertura (barra 13:00) no puede existir en barras previas."""
        df = synth()
        lv = build_levels(df)
        hour = df["timestamp"].dt.hour.to_numpy()
        for name in ("ORB low (13h)", "ORB high (13h)", "IB high (13-14h)",
                     "IB low (13-14h)", "Session open (13h)"):
            before = lv[name][hour < LEVELS_MIN_HOUR[name]]
            assert not np.isfinite(before).any(), f"{name} visible antes de formarse"

    def test_all_session_levels_blank_outside_session(self):
        df = synth()
        lv = build_levels(df)
        hour = df["timestamp"].dt.hour.to_numpy()
        outside = (hour < 13) | (hour > 19)
        for name in ("ORB low (13h)", "ORB high (13h)", "IB high (13-14h)",
                     "Overnight low", "Session open (13h)"):
            assert not np.isfinite(lv[name][outside]).any(), f"{name} fuera de sesión"

    def test_declared_min_hours_cover_every_level(self):
        """Todo nivel construido debe declarar su hora mínima (si no, es sospechoso)."""
        lv = build_levels(synth())
        assert set(lv) == set(LEVELS_MIN_HOUR)


class TestTriggers:
    def test_cross_requires_previous_bar_above(self):
        lv = np.array([10.0, 10.0, 10.0])
        close = np.array([11.0, 9.0, 9.5])
        high = low = close.copy()
        prev = np.array([np.nan, 11.0, 9.0])
        t = triggers(lv, close, high, low, prev)
        assert t["cruce debajo"][1] and not t["cruce debajo"][2]

    def test_close_below_is_any_bar_under_level(self):
        lv = np.array([10.0, 10.0])
        close = np.array([9.0, 9.0])
        t = triggers(lv, close, close, close, np.array([9.0, 9.0]))
        assert t["cierre debajo"].all()

    def test_nan_level_never_triggers(self):
        lv = np.array([np.nan, np.nan])
        close = np.array([5.0, 5.0])
        t = triggers(lv, close, close, close, close)
        for mask in t.values():
            assert not np.asarray(mask, bool).any()


class TestEntriesFor:
    def test_respects_window(self):
        df = synth()
        p = _prep(df)
        open_win = entries_for(p, "Prev-day low", "cierre debajo", window=None)
        ny_win = entries_for(p, "Prev-day low", "cierre debajo", window=(13, 19))
        assert len(ny_win) <= len(open_win)
        hours = p["hour"][ny_win]
        assert ((hours >= 13) & (hours <= 19)).all()

    def test_max_one_entry_per_day(self):
        df = synth()
        p = _prep(df)
        ent = entries_for(p, "Prev-day low", "cierre debajo", window=None)
        days = p["day"].iloc[ent]
        assert days.duplicated().sum() == 0

    def test_session_level_cannot_be_traded_before_it_exists(self):
        """El rango de apertura no puede dar entradas antes de las 14:00."""
        df = synth()
        p = _prep(df)
        ent = entries_for(p, "ORB low (13h)", "cierre debajo", window=None)
        assert len(ent) > 0, "el escenario sintético debería generar señales"
        assert (p["hour"][ent] >= 14).all()


class TestWindowAnalysis:
    def test_scan_windows_returns_expected_columns(self):
        df = synth()
        t = scan_windows(df, [("Prev-day low", "cierre debajo")],
                         [("24h", None), ("13-19", (13, 19))])
        assert set(t.columns) >= {"celda", "ventana", "n", "R/trade", "IS", "OOS"}
        assert set(t["ventana"]) <= {"24h", "13-19"}
        assert "24h" in set(t["ventana"])

    def test_hourly_profile_buckets_sum_to_total(self):
        df = synth()
        h = hourly_profile(df, "Prev-day low", "cierre debajo")
        if len(h):
            n_tot = entries_for(_prep(df), "Prev-day low", "cierre debajo", window=None)
            assert h["n"].sum() == len(n_tot)
            assert h["hora_utc"].between(0, 23).all()

    def test_session_level_identical_across_windows(self):
        """Un nivel de sesión no se ve afectado por la ventana: se autolimita."""
        df = synth()
        t = scan_windows(df, [("ORB low (13h)", "cierre debajo")],
                         [("24h", None), ("13-19", (13, 19)), ("6-20", (6, 20))])
        assert t["n"].nunique() == 1
