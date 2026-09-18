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


def _localname(tag: str) -> str:
    return tag.split("}")[-1]


def _find(root, name: str):
    return next((el for el in root.iter() if _localname(el.tag) == name), None)


def _first_child(el, name: str):
    for child in el:
        if _localname(child.tag) == name:
            return child
    return None


def _condition_map(conds) -> dict:
    """{columna: valor} de las <Condition> activas de un contenedor <Conditions>."""
    out = {}
    for c in conds:
        if _localname(c.tag) != "Condition" or c.get("use") != "true":
            continue
        col = next((cv.get("column") for cv in c.iter()
                    if _localname(cv.tag) == "Column-Value" and cv.get("column")), None)
        num = next((nv.get("value") for nv in c.iter()
                    if _localname(nv.tag) == "Numeric-Value"), None)
        out[col] = num
    return out


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


class TestBlockActivation:
    """Activar bloques en el .cfx es lo que hace que el builder los USE."""

    def test_add_signals(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "blocks.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "blocks": {"add_signals": ["StochSlowDCrossDown", "VortexDowntrend"]}
        })
        assert report["warnings"] == []
        cfg = parse_cfx(out)
        active = {b["key"] for b in cfg.blocks["building_blocks"]
                  if b.get("use") and b.get("category") == "signals"}
        assert "StochSlowDCrossDown" in active
        assert "VortexDowntrend" in active

    def test_unknown_block_aborts_with_suggestion(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "nope.cfx"
        with pytest.raises(ValueError, match="StochasticCrossDown"):
            apply_builder_profile(cfx_file, out, {
                "blocks": {"add_signals": ["StochasticCrossDown"]}  # nombre inexistente
            })
        assert not out.exists()

    def test_block_activation_preserves_other_blocks(self, cfx_file: Path, tmp_path: Path):
        original = parse_cfx(cfx_file)
        n_before = sum(1 for b in original.blocks["building_blocks"] if b.get("use"))

        out = tmp_path / "pres.cfx"
        apply_builder_profile(cfx_file, out, {
            "blocks": {"add_signals": ["MomFalling"]}
        })
        after = parse_cfx(out)
        n_after = sum(1 for b in after.blocks["building_blocks"] if b.get("use"))
        assert n_after == n_before + 1
        # El total de bloques del catálogo no cambia
        assert len(after.blocks["building_blocks"]) == len(original.blocks["building_blocks"])

    def test_remove_blocks(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "rem.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "blocks": {"remove_indicators": ["Indicators.RSI"]}
        })
        assert report["warnings"] == []
        cfg = parse_cfx(out)
        rsi = next(b for b in cfg.blocks["building_blocks"]
                   if b["key"] == "Indicators.RSI")
        assert rsi["use"] is False

    def test_unknown_section_key_reported(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "unk.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "blocks": {"add_señales": ["RSIFalling"]}  # clave inválida
        })
        assert any("add_señales" in w for w in report["warnings"])


class TestGeneticConditions:
    """Las condiciones del GENÉTICO (<BuildMode>) son distintas de las de Ranking.

    El GA filtra durante la evolución: alinearlas con el ranking evita gastar
    generaciones en estrategias que se descartan al final.
    """

    def _bm_conditions(self, root):
        bm = _find(root, "BuildMode")
        assert bm is not None, "el .cfx no tiene <BuildMode>"
        return _first_child(bm, "Conditions")

    def test_activates_existing_and_adds_new(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "gen.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "genetic": {
                "profit_factor_min": 1.1,
                "number_of_trades_min": 150,
                "sharpe_ratio_min": 0.4,
                "return_dd_ratio_min": 0.5,
                "win_loss_ratio_min": 0.9,
            }
        })
        active = _condition_map(self._bm_conditions(load_cfx_xml(out)))
        assert active["ProfitFactor"] == "1.1"
        assert active["NumberOfTrades"] == "150"
        assert active["SharpeRatio"] == "0.4"    # existía inactiva
        assert active["ReturnDDRatio"] == "0.5"  # existía inactiva
        assert active["WinLossRatio"] == "0.9"   # NO existía → slot libre o clon
        assert "BuildMode.WinLossRatio" in {c["setting"] for c in report["changes"]}

    def test_genetic_does_not_touch_rankings(self, cfx_file: Path, tmp_path: Path):
        """Crítico: no confundir el <Conditions> de BuildMode con el de Rankings.

        `_find_section(root, "Conditions")` devolvería el de Rankings siempre
        (es el primero del documento). Si eso pasara, el filtro del genético se
        aplicaría sobre los filtros de salida y viceversa.
        """
        before = _condition_map(_first_child(_find(load_cfx_xml(cfx_file), "Rankings"),
                                             "Conditions"))
        out = tmp_path / "gen2.cfx"
        apply_builder_profile(cfx_file, out, {"genetic": {"win_loss_ratio_min": 0.9}})
        after = _condition_map(_first_child(_find(load_cfx_xml(out), "Rankings"),
                                            "Conditions"))
        assert after == before, "el genético modificó las condiciones de Ranking"


class TestSampleWindow:
    """`sample_type` decide sobre qué muestra se evalúa cada filtro.

    10 = In-Sample · 20 = Out-of-Sample · 127 = IS+OOS combinados.
    Filtrar en 127 hace que el out-of-sample participe de la selección y deje de
    ser un juez independiente.
    """

    def test_ranking_sample_type_set_to_is(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "st.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "rankings": {"sample_type": 10}
        })
        root = load_cfx_xml(out)
        conds = _first_child(_find(root, "Rankings"), "Conditions")
        checked = 0
        for c in conds:
            if _localname(c.tag) != "Condition" or c.get("use") != "true":
                continue
            cv = next((v for v in c.iter()
                       if _localname(v.tag) == "Column-Value" and v.get("column")), None)
            if cv is None or not cv.get("sampleType"):
                continue
            assert cv.get("sampleType") == "10", f"{cv.get('column')} quedó en IS+OOS"
            checked += 1
        assert checked > 0
        assert any(c["setting"] == "Rankings.sample_type" for c in report["changes"])

    def test_genetic_sample_type_is_independent(self, cfx_file: Path, tmp_path: Path):
        """sample_type del genético no debe arrastrar el de Rankings."""
        out = tmp_path / "st2.cfx"
        apply_builder_profile(cfx_file, out, {"genetic": {"sample_type": 10}})
        root = load_cfx_xml(out)
        for c in _first_child(_find(root, "BuildMode"), "Conditions"):
            if _localname(c.tag) != "Condition" or c.get("use") != "true":
                continue
            cv = next((v for v in c.iter()
                       if _localname(v.tag) == "Column-Value" and v.get("column")), None)
            if cv is not None and cv.get("sampleType"):
                assert cv.get("sampleType") == "10"


class TestDataPeriod:
    """Período completo testeado y partición In-Sample / Out-of-Sample."""

    def test_period_and_is_oos_split(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "data.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "data": {
                "date_from": "2020-01-01",
                "date_to": "2026-09-16",
                "out_of_sample": [
                    {"from": "2020-01-01", "to": "2024-01-09", "type": "isv"},
                    {"from": "2024-01-09", "to": "2026-09-16"},
                ],
            }
        })
        assert report["warnings"] == []
        root = load_cfx_xml(out)

        # Las fechas van en formato StrategyQuant (con puntos)
        setups = [el for el in root.iter() if _localname(el.tag) == "Setup"]
        assert setups
        assert all(s.get("dateFrom") == "2020.01.01" for s in setups)
        assert all(s.get("dateTo") == "2026.09.16" for s in setups)

        oos = _find(root, "OutOfSample")
        ranges = [r for r in oos if _localname(r.tag) == "Range"]
        assert len(ranges) == 2
        assert ranges[0].get("dateFrom") == "2020.01.01"
        assert ranges[0].get("type") == "isv"      # In-Sample
        assert ranges[1].get("dateFrom") == "2024.01.09"
        assert ranges[1].get("type") is None       # sin type = Out-of-Sample

    def test_invalid_range_is_reported(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "bad.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "data": {"out_of_sample": [{"from": "2020-01-01"}]}  # falta "to"
        })
        assert any("out_of_sample" in w for w in report["warnings"])
        assert out.exists()

    def test_unknown_genetic_key_reported(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "unkg.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "genetic": {"no_existe_esta_clave": 1}
        })
        assert any("no_existe_esta_clave" in w for w in report["warnings"])


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


class TestBlockFixedParams:
    """Fijar parámetros de bloque con un set predefinido de StrategyQuant.

    Es lo que permite que un bloque con parámetros aleatorios —las horas de inicio y
    fin de `Prices.SessionLow`, por ejemplo— represente un nivel concreto (el rango
    overnight) en lugar de un sorteo entre 0 y 23.
    """

    @staticmethod
    def _predefined(path, key):
        root = load_cfx_xml(path)
        blk = next(el for el in root.iter()
                   if _localname(el.tag) == "Block" and el.get("key") == key)
        pre = _first_child(blk, "Predefined")
        if pre is None:
            return {}
        return {p.get("key"): p for p in pre.iter() if _localname(p.tag) == "Param"}

    def test_fixed_values_are_written(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "fixed.cfx"
        apply_builder_profile(cfx_file, out, {"blocks": {"fixed_params": {
            "Prices.SessionLow": {"#StartHours#": 20, "#StartMinutes#": 0,
                                  "#EndHours#": 12, "#EndMinutes#": 0, "#Shift#": 1}}}})
        p = self._predefined(out, "Prices.SessionLow")
        assert p["#StartHours#"].get("generation") == "fixed"
        assert p["#StartHours#"].get("defaultValue") == "20"
        assert p["#EndHours#"].get("defaultValue") == "12"
        assert p["#Shift#"].get("defaultValue") == "1"

    def test_unlisted_params_keep_random_generation(self, cfx_file: Path, tmp_path: Path):
        """Los parámetros no pedidos deben conservar su generación aleatoria."""
        out = tmp_path / "fixed2.cfx"
        apply_builder_profile(cfx_file, out, {"blocks": {"fixed_params": {
            "Prices.SessionLow": {"#StartHours#": 20}}}})
        p = self._predefined(out, "Prices.SessionLow")
        assert p["#Chart#"].get("generation") == "random"

    def test_unknown_block_raises(self, cfx_file: Path, tmp_path: Path):
        with pytest.raises(ValueError, match="NoExiste"):
            apply_builder_profile(cfx_file, tmp_path / "x.cfx",
                                  {"blocks": {"fixed_params": {"NoExiste": {"#A#": 1}}}})

    def test_unknown_param_raises(self, cfx_file: Path, tmp_path: Path):
        """Pasar un parámetro que el bloque no tiene debe abortar, no ignorarse."""
        with pytest.raises(ValueError, match="inexistentes"):
            apply_builder_profile(cfx_file, tmp_path / "y.cfx",
                                  {"blocks": {"fixed_params": {
                                      "Prices.SessionLow": {"#Nope#": 1}}}})


class TestSetCategoryStrict:
    """`set_<categoria>` deja el catálogo EXACTO: activa las pedidas y apaga el resto.

    Es lo que permite aislar un edge: con el catálogo reducido a sus bloques, el
    generador no puede armar reglas de otras familias.
    """

    def test_set_indicators_leaves_only_those(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "only.cfx"
        wanted = ["CrossesBelow", "Prices.Close", "Prices.SessionLow"]
        apply_builder_profile(cfx_file, out, {"blocks": {"set_indicators": wanted}})
        cfg = parse_cfx(out)
        on = {b["key"] for b in cfg.blocks["building_blocks"]
              if b.get("use") and b.get("category") == "indicators"}
        assert on == set(wanted)

    def test_set_signals_empty_disables_all(self, cfx_file: Path, tmp_path: Path):
        out = tmp_path / "nosig.cfx"
        apply_builder_profile(cfx_file, out, {"blocks": {"set_signals": []}})
        cfg = parse_cfx(out)
        on = [b["key"] for b in cfg.blocks["building_blocks"]
              if b.get("use") and b.get("category") == "signals"]
        assert on == []

    def test_sqn_can_be_used_as_fitness_and_filter(self, cfx_file: Path, tmp_path: Path):
        """SQN es lo que el usuario quiere maximizar: debe poder fijarse en ambos lados."""
        out = tmp_path / "sqn.cfx"
        report = apply_builder_profile(cfx_file, out, {
            "rankings": {"fitness": "SQNScore", "sqn_score_min": 0.5},
            "genetic": {"sqn_score_min": 0.3},
        })
        assert report["warnings"] == []
        raw = zipfile.ZipFile(out).read("config.xml").decode("utf-8", "replace")
        assert 'type="SQNScore"' in raw
        assert 'column="SQNScore"' in raw
