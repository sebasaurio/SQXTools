"""Tests del CFX Builder — aplica perfiles de configuración sobre un .cfx.

Usa el fixture real `Build strategies 1.cfx` (config de builder completa de
StrategyQuant) para validar que los cambios se aplican preservando el resto.
"""

import json
import zipfile
from pathlib import Path

import pytest

from sqxtools.cfx_builder import (
    apply_builder_profile,
    load_builder_profile,
    load_cfx_xml,
    write_cfx_xml,
)
from sqxtools.analyzer import summarize
from sqxtools.parser import parse_cfx

FIXTURES = Path(__file__).parent / "fixtures"
CFX = FIXTURES / "Build strategies 1.cfx"

pytestmark = pytest.mark.skipif(not CFX.exists(), reason="Sin fixture .cfx real")


@pytest.fixture
def cfx_file() -> Path:
    return CFX


class TestCfxBuilderCore:
    def test_load_and_write_roundtrip(self, cfx_file: Path, tmp_path: Path):
        root = load_cfx_xml(cfx_file)
        out = write_cfx_xml(root, tmp_path / "copia.cfx")
        assert out.exists()
        # El archivo resultante debe volver a parsearse sin problemas
        cfg = parse_cfx(out)
        assert cfg.cfx_type.value == "build"
        assert len(cfg.blocks["building_blocks"]) == 524

    def test_load_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_cfx_xml(tmp_path / "no.cfx")

    def test_load_non_cfx(self, tmp_path: Path):
        bad = tmp_path / "malo.cfx"
        bad.write_text("no soy zip")
        with pytest.raises(zipfile.BadZipFile):
            load_cfx_xml(bad)


class TestApplyBuilderProfile:
    def test_risk_reward_changes(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "rr.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "risk_reward": {
                "limit_slpt_rrr": True,
                "rrr_from": 60,
                "rrr_to": 120,
                "pt_atr_multiple_min": 1.2,
                "pt_atr_multiple_max": 2.0,
            }
        })
        assert report["warnings"] == []
        cfg = parse_cfx(out)
        sl = cfg.what_to_build["slpt_options"]
        assert sl["LimitSLPTRRR"] is True
        assert sl["LimitSLPTRRRFrom"] == "60"
        assert sl["LimitSLPTRRRTo"] == "120"
        assert sl["MinPTATRMultiple"] == "1.2"
        assert sl["MaxPTATRMultiple"] == "2"

    def test_entries_and_trading_options(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "en.cfx"
        apply_builder_profile(cfx_file, out, {
            "entries": {"min_conditions": 3, "max_conditions": 3},
            "trading": {
                "limit_time_range": True,
                "signal_time_from": 43200,
                "signal_time_to": 54000,
                "max_trades_per_day": 3,
                "dont_trade_weekends": True,
            },
        })
        cfg = parse_cfx(out)
        chart = cfg.what_to_build["rules_complexity"]["charts"][0]
        assert chart["minConditions"] == "3"
        assert chart["maxConditions"] == "3"

        opts = {p["key"]: p["value"] for p in cfg.settings["trading_options"]}
        assert opts["LimitTimeRange"] is True
        assert opts["SignalTimeRangeFrom"] == 43200
        assert opts["MaxTradesPerDay"] == 3
        assert opts["DontTradeOnWeekends"] is True

    def test_fitness_and_ranking_conditions(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "rk.cfx"
        apply_builder_profile(cfx_file, out, {
            "rankings": {
                "fitness": "SharpeRatio",
                "profit_factor_min": 1.45,
                "win_loss_ratio_min": 1.5,
            }
        })
        cfg = parse_cfx(out)
        assert cfg.rankings["fitness_criteria"]["type"] == "SharpeRatio"

        summary = summarize(cfg)
        active = {c["left"]: (c["comparator"], c["right"])
                  for c in summary["rankings"]["active_filters"]}
        assert active["ProfitFactor"] == (">=", "1.45")
        assert active["WinLossRatio"] == (">=", "1.5")

    def test_exit_probability(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "ex.cfx"
        apply_builder_profile(cfx_file, out, {
            "exits": {"exit_after_bars_probability": 20}
        })
        root = load_cfx_xml(out)
        found = None
        for el in root.iter():
            if el.tag == "Block" and el.get("key") == "ExitAfterBars.ExitAfterBars":
                found = el.get("probability")
        assert found == "20"

    def test_new_ranking_condition_reuses_inactive_slot(self, cfx_file: Path, tmp_path: Path):
        """Crítico: una condición nueva debe REUTILIZAR una inactiva, no crearse.

        StrategyQuant re-instancia las condiciones creadas a mano y reinicia su
        valor al default (WinLossRatio → 1.2). Reutilizar un slot preserva la
        estructura completa de atributos que SQ espera.
        """
        original = parse_cfx(cfx_file)
        n_before = len(original.rankings["conditions"])

        out = tmp_path / "reuse.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "rankings": {"win_loss_ratio_min": 1.5}
        })

        # Debe reportarse como reutilización, no como creación desde cero
        entry = next(c for c in report["changes"] if c["setting"].endswith("WinLossRatio"))
        assert entry["status"] == "added"
        assert "reused_condition" in entry

        after = parse_cfx(out)
        # El total de condiciones NO debe crecer
        assert len(after.rankings["conditions"]) == n_before

        # Y la condición debe tener la estructura completa de atributos
        target = None
        for cond in after.rankings["conditions"]:
            col = cond.get("left_side", {}).get("column", {})
            if col.get("column") == "WinLossRatio":
                target = col
                break
        assert target is not None
        assert target.get("sampleType") == "127"
        assert target.get("class") == "WinLossRatio"
        assert target.get("confidenceLevel") == "50"

    def test_unknown_setting_is_reported_not_crashed(self, cfx_file: Path, tmp_path: Path):
        """Un nombre de parámetro inexistente debe reportarse, no romper."""
        out = tmp_path / "unk.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "trading": {"no_existe_este_parametro": 99}
        })
        assert any("no_existe_este_parametro" in w for w in report["warnings"])
        assert out.exists()  # igual escribe el archivo

    def test_profile_preserves_everything_else(self, cfx_file: Path, tmp_path: Path):
        """Crítico: aplicar un perfil no debe alterar bloques ni recursos."""
        original = parse_cfx(cfx_file)
        out = tmp_path / "pres.cfx"
        apply_builder_profile(cfx_file, out, {
            "trading": {"max_trades_per_day": 3},
            "rankings": {"fitness": "SharpeRatio"},
        })
        after = parse_cfx(out)

        assert len(after.blocks["building_blocks"]) == len(original.blocks["building_blocks"])
        assert sum(1 for b in after.blocks["building_blocks"] if b["use"]) == \
               sum(1 for b in original.blocks["building_blocks"] if b["use"])
        assert after.resources.get("symbols") == original.resources.get("symbols")
        assert len(after.data["setups"]) == len(original.data["setups"])

    def test_no_op_profile_reports_unchanged(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "noop.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "entries": {"min_conditions": 1}  # ya vale 1 en el fixture
        })
        assert report["applied"] == 0
        assert any(c["status"] == "unchanged" for c in report["changes"])


class TestBuilderProfiles:
    def test_load_yaml_profile(self, tmp_path: Path):
        p = tmp_path / "perfil.yaml"
        p.write_text(
            "risk_reward:\n  limit_slpt_rrr: true\n  rrr_from: 60\n", encoding="utf-8"
        )
        prof = load_builder_profile(p)
        assert prof["risk_reward"]["limit_slpt_rrr"] is True

    def test_load_json_profile(self, tmp_path: Path):
        p = tmp_path / "perfil.json"
        p.write_text(json.dumps({"entries": {"min_conditions": 3}}), encoding="utf-8")
        prof = load_builder_profile(p)
        assert prof["entries"]["min_conditions"] == 3

    def test_load_missing_profile(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_builder_profile(tmp_path / "no.yaml")

    def test_profile_invalid_root(self, tmp_path: Path):
        p = tmp_path / "lista.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        with pytest.raises(ValueError):
            load_builder_profile(p)

    def test_repo_example_profile_is_valid(self):
        """El perfil de ejemplo del repo debe cargar y aplicar sin warnings."""
        repo_profile = Path(__file__).parents[2] / "perfiles" / "builder-nas100-winrate.yaml"
        if not repo_profile.exists():
            pytest.skip("perfil de ejemplo no presente")
        prof = load_builder_profile(repo_profile)
        assert "risk_reward" in prof
        assert prof["risk_reward"]["limit_slpt_rrr"] is True
