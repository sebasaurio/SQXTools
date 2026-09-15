"""Tests de reality_check."""
from pathlib import Path

import pytest

from sqxtools.reality_check import (
    Finding,
    RealityReport,
    check_breakeven_con_costos,
    check_min_pt_vs_spread,
    check_spread_vs_mc,
    check_swap_direccion,
    check_ventana_vs_sesion,
    _norm,
)

PROJECT = Path("/home/sebas/.hermes/cache/documents/doc_998bb3392d1f_NASDAQ - SELL - H1 BotPulse Academy.cfx")
V10 = Path("/home/sebas/SQXTools/output/v10_scalping_h1.cfx")
SPEC_CSV = Path("/mnt/c/Users/sebas/AppData/Roaming/MetaQuotes/Terminal/D0E8209F77C8CF37AD8BF550E51FF075/MQL5/Files/sqx_specs.csv")
SESS_CSV = Path("/mnt/c/Users/sebas/AppData/Roaming/MetaQuotes/Terminal/D0E8209F77C8CF37AD8BF550E51FF075/MQL5/Files/sqx_sessions.csv")


def _specs_ustec112():
    specs = {
        "USTEC": {"real_name": "USTECm", "point": 0.01, "digits": 2,
                  "spread": 112, "swap_long": -589.1, "swap_short": 0.0},
    }
    return specs


def _sessions_ustec():
    return {"USTECm": [
        ("Mon", "00:00", "21:00"), ("Mon", "22:00", "00:00"),
        ("Tue", "00:00", "21:00"), ("Tue", "22:00", "00:00"),
        ("Wed", "00:00", "21:00"), ("Wed", "22:00", "00:00"),
        ("Thu", "00:00", "21:00"), ("Thu", "22:00", "00:00"),
        ("Fri", "00:00", "20:55"),
    ]}


class TestNorm:
    def test_variants(self):
        assert _norm("USTECm") == "USTEC"
        assert _norm("USTEC_exness") == "USTEC"
        assert _norm("USTECm_exness") == "USTEC"
        assert _norm("US30m_exness") == "US30"  # quita m tras quitar _exness


class TestCheckMinPt:
    def test_pt_ok(self):
        rep = RealityReport()
        check_min_pt_vs_spread(rep, _fake_cfg_minpt("200"), _specs_ustec112(), "USTEC")
        assert rep.findings[0].code == "pt_ok_spread"

    def test_pt_ajustado(self):
        rep = RealityReport()
        check_min_pt_vs_spread(rep, _fake_cfg_minpt("140"), _specs_ustec112(), "USTEC")
        assert rep.findings[0].code == "pt_ajustado_spread"

    def test_pt_bajo(self):
        rep = RealityReport()
        check_min_pt_vs_spread(rep, _fake_cfg_minpt("100"), _specs_ustec112(), "USTEC")
        assert rep.findings[0].severity == "error"
        assert "1.2×" in rep.findings[0].message

    def test_spread_cero_skips(self):
        specs = _specs_ustec112()
        specs["USTEC"]["spread"] = 0
        rep = RealityReport()
        check_min_pt_vs_spread(rep, _fake_cfg_minpt("140"), specs, "USTEC")
        assert rep.findings[0].code == "spread_desconocido"


def _fake_cfg_minpt(v):
    class C:
        what_to_build = {"slpt_options": {"MinPTInPips": v, "LimitSLPTRRRFrom": "55",
                                          "LimitSLPTRRRTo": "85"}}
        settings = {"trading_options": [
            {"key": "LimitTimeRange", "value": True},
            {"key": "SignalTimeRangeFrom", "value": 43200},
            {"key": "SignalTimeRangeTo", "value": 72000},
        ]}
    return C()


class TestVentana:
    def test_ventana_dentro(self):
        rep = RealityReport()
        check_ventana_vs_sesion(rep, _fake_cfg_minpt("140"), _sessions_ustec(), "USTECm")
        assert rep.findings[0].code == "ventana_ok"

    def test_ventana_fuera(self):
        rep = RealityReport()
        cfg = _fake_cfg_minpt("140")
        cfg.settings = {"trading_options": [
            {"key": "LimitTimeRange", "value": True},
            {"key": "SignalTimeRangeFrom", "value": 75600},  # 21:00
            {"key": "SignalTimeRangeTo", "value": 79200},    # 22:00
        ]}
        check_ventana_vs_sesion(rep, cfg, _sessions_ustec(), "USTECm")
        assert rep.findings[0].code == "ventana_fuera_sesion"
        assert rep.findings[0].severity == "error"


class TestSwap:
    def test_short_libre(self):
        rep = RealityReport()
        check_swap_direccion(rep, None, _specs_ustec112(), "USTEC", "short")
        assert rep.findings[0].severity == "ok"

    def test_short_costo(self):
        specs = _specs_ustec112()
        specs["USTEC"]["swap_short"] = -225.0
        rep = RealityReport()
        check_swap_direccion(rep, None, specs, "USTEC", "short")
        assert rep.findings[0].severity == "warning"


class TestBreakeven:
    def test_info_con_rrr(self):
        rep = RealityReport()
        check_breakeven_con_costos(rep, _fake_cfg_minpt("140"), _specs_ustec112(), "USTEC")
        assert rep.findings[0].code == "breakeven_costos"
        assert "54.1" in rep.findings[0].message  # 1/(1+0.85) = 54.05%


class TestMcSpread:
    @pytest.mark.skipif(not PROJECT.exists(), reason="project real no disponible")
    def test_detecta_spread_irreal(self):
        rep = RealityReport()
        check_spread_vs_mc(rep, str(PROJECT), _specs_ustec112(), "USTEC")
        codes = {f.code for f in rep.findings}
        assert "spread_mc_irreal" in codes
        f = next(f for f in rep.findings if f.code == "spread_mc_irreal")
        assert "37" in f.message  # 112/3 ≈ 37×

    def test_sin_project(self):
        rep = RealityReport()
        check_spread_vs_mc(rep, "/no/existe.cfx", _specs_ustec112(), "USTEC")
        assert rep.findings == []


class TestFinding:
    def test_render_multilinea(self):
        f = Finding("error", "c", "SYM", "mensaje", "detalle")
        assert "🔴" in f.render() and "detalle" in f.render()

    def test_report_head(self):
        rep = RealityReport()
        rep.findings.append(Finding("error", "c", "S", "m"))
        assert "1 error(es)" in rep.render()
