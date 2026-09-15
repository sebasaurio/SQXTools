"""Tests de results_analyzer."""
import csv
from pathlib import Path

from sqxtools.results_analyzer import (
    _canonical,
    _num,
    analyze_results,
    builder_thresholds,
    funnel,
    load_strategies_csv,
    margin_over_filters,
)


def _write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys(), delimiter=";")
        w.writeheader()
        w.writerows(rows)
    return path


SAMPLE = [
    {"Strategy Name": "S1", "Net Profit": "1500", "Profit Factor": "1.85",
     "Win/Loss Ratio": "1.72", "# Trades": "410", "Max Drawdown %": "8.2",
     "Time in Market": "2.1"},
    {"Strategy Name": "S2", "Net Profit": "900", "Profit Factor": "1.52",
     "Win/Loss Ratio": "1.38", "# Trades": "320", "Max Drawdown %": "11.4",
     "Time in Market": "3.4"},
]


class TestParsing:
    def test_canonical(self):
        assert _canonical("Profit Factor") == "profitfactor"
        assert _canonical("# Trades") == "numberoftrades"
        assert _canonical("Win/Loss Ratio") == "winlossratio"
        assert _canonical("Columna Rara") is None

    def test_num(self):
        assert _num("1,500.5") == 1500.5
        assert _num("8.2%") == 8.2
        assert _num("$900") == 900.0
        assert _num("-") is None

    def test_load_delim(self, tmp_path):
        p = _write_csv(tmp_path / "x.csv", SAMPLE)
        rows, unmapped = load_strategies_csv(p)
        assert len(rows) == 2
        assert rows[0]["profitfactor"] == 1.85
        assert rows[0]["strategyname"] == "S1"
        assert unmapped == [] or "Strategy Name" not in unmapped


class TestThresholds:
    def test_desde_v10(self):
        v10 = Path("/home/sebas/SQXTools/output/v10_scalping_h1.cfx")
        if not v10.exists():
            import pytest
            pytest.skip("v10 no disponible")
        thr = builder_thresholds(v10)
        assert "profitfactor" in thr
        assert thr["profitfactor"] == (">=", 1.3)
        assert "numberoftrades" in thr

    def test_vacio(self):
        assert builder_thresholds(None) == {}


class TestMargin:
    def test_tight_pass(self):
        thr = {"numberoftrades": (">=", 300), "profitfactor": (">=", 1.3)}
        rows, _ = load_strategies_csv(_write_csv(Path("/tmp/m.csv"), SAMPLE))
        out = margin_over_filters(rows, thr)
        assert any("numberoftrades" in o and "1/2" in o for o in out)
        assert any("profitfactor" in o and "0/3" in o for o in out)


class TestFunnel:
    def test_mortalidad(self):
        out = funnel([("Build", [{"a": 1}] * 100), ("SeqOpt", [{"a": 1}] * 40)])
        assert "100" in out[0]
        assert "60 eliminados" in out[1] and "60%" in out[1]


class TestAnalyze:
    def test_reporte_completo(self, tmp_path):
        p = _write_csv(tmp_path / "s.csv", SAMPLE)
        out = analyze_results(p)
        assert "Distribución" in out
        assert "profitfactor" in out
        assert "Sugerencias" in out

    def test_vacio(self, tmp_path):
        p = _write_csv(tmp_path / "e.csv", [{"Strategy Name": "x"}])
        out = analyze_results(p)
        assert "ERROR" in out
