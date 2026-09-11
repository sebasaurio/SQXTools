"""Tests para el parser y builder de .sqb (Block Settings de StrategyQuant).

Usa un .sqb sintético con la estructura real de StrategyQuant para no depender
de archivos externos ni de una instalación de SQX.
"""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pytest

from sqxtools.sqb_parser import parse_sqb, get_block_summary
from sqxtools.sqb_builder import (
    build_recommended_sqb,
    build_from_profile,
    dump_catalog,
    get_block_definition,
    list_blocks,
    load_sqb_template,
    load_profile,
    save_profile,
    validate_selection,
    diff_sqb,
)


# === .sqb sintético con la estructura real de StrategyQuant ===

SQB_XML = """<?xml version="1.0" encoding="utf-8"?>
<Blocks type="simple" version="144.2938">
  <Calibration useMaxSteps="true" maxSteps="50" calibrateBeforeStart="false" />
  <BuildingBlocks>
    <Block key="RSIFalling" weight="1" use="false" category="signals">
      <Generated weight="1">
        <Param key="#Chart#" name="Chart" type="data" paramType="null" generation="random" minValue="-1000003" maxValue="-1000004" step="1" />
        <Param key="#ComputedFrom#" name="ComputedFrom" type="int" paramType="null" generation="random" minValue="-1000003" maxValue="-1000004" step="1" />
        <Param key="#Period#" name="Period" type="int" paramType="null" generation="random" minValue="7" maxValue="50" step="1" />
        <Param key="#Shift#" name="Shift" type="int" paramType="null" generation="random" minValue="-1000001" maxValue="-1000002" step="1" />
      </Generated>
      <Predefined changed="false">
        <Params name="Default set 1" weight="1">
          <Param key="#Period#" name="Period" type="int" generation="fixed" defaultValue="14" />
        </Params>
      </Predefined>
    </Block>
    <Block key="IsDowntrend" weight="1" use="false" category="signals">
      <Generated weight="1">
        <Param key="#Chart#" name="Chart" type="data" paramType="null" generation="random" minValue="-1000003" maxValue="-1000004" step="1" />
        <Param key="#Method#" name="Method" type="int" paramType="null" generation="random" minValue="-1000003" maxValue="-1000004" step="1" />
      </Generated>
      <Predefined changed="false" />
    </Block>
    <Block key="Indicators.ATR" weight="1" use="false" category="indicators"
           indicatorMin="0" indicatorMax="500" indicatorStep="0.5">
      <Generated weight="1">
        <Param key="#Chart#" name="Chart" type="data" paramType="null" generation="random" minValue="-1000003" maxValue="-1000004" step="1" />
        <Param key="#Period#" name="Period" type="int" paramType="null" generation="random" minValue="7" maxValue="50" step="1" />
      </Generated>
      <Predefined changed="false" />
    </Block>
    <Block key="Prices.Close" weight="1" use="false" category="indicators">
      <Generated weight="1">
        <Param key="#Chart#" name="Chart" type="data" paramType="null" generation="random" minValue="-1000003" maxValue="-1000004" step="1" />
        <Param key="#Shift#" name="Shift" type="int" paramType="null" generation="random" minValue="-1000001" maxValue="-1000002" step="1" />
      </Generated>
      <Predefined changed="false" />
    </Block>
    <Block key="Stop/Limit Price Ranges.ATR" weight="1" use="false" category="stopLimitBlocks">
      <Generated weight="1">
        <Param key="#Chart#" name="Chart" type="data" paramType="null" generation="random" minValue="-1000003" maxValue="-1000004" step="1" />
        <Param key="#Period#" name="Period" type="int" paramType="null" generation="random" minValue="7" maxValue="50" step="1" />
      </Generated>
      <Predefined changed="false" />
    </Block>
  </BuildingBlocks>
  <OrderTypes>
    <Block key="EnterAtStop" weight="1" use="false" category="orderTypes" />
    <Block key="EnterAtLimit" weight="1" use="false" category="orderTypes" />
  </OrderTypes>
  <ExitTypes>
    <Block key="StopLoss.StopLoss" weight="1" use="false" probability="100" category="exitTypes" />
    <Block key="ProfitTarget.ProfitTarget" weight="1" use="false" probability="100" category="exitTypes" />
  </ExitTypes>
  <CustomData showAll="false" />
</Blocks>
"""


@pytest.fixture
def sqb_file(tmp_path: Path) -> Path:
    """Crea un .sqb sintético en disco."""
    path = tmp_path / "BlockSettings.sqb"
    root = ET.fromstring(SQB_XML)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("config.xml", "w") as f:
            ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=True)
    return path


# === Tests del parser ===

class TestSqbParser:
    def test_parse_basic(self, sqb_file: Path):
        sqb = parse_sqb(sqb_file)
        assert sqb.filename == "BlockSettings.sqb"
        assert sqb.block_type == "simple"
        assert sqb.version == "144.2938"
        assert len(sqb.building_blocks) == 5

    def test_calibration(self, sqb_file: Path):
        sqb = parse_sqb(sqb_file)
        assert sqb.calibration["useMaxSteps"] == "true"
        assert sqb.calibration["maxSteps"] == "50"

    def test_order_and_exit_types(self, sqb_file: Path):
        sqb = parse_sqb(sqb_file)
        assert [b.key for b in sqb.order_types] == ["EnterAtStop", "EnterAtLimit"]
        assert [b.key for b in sqb.exit_types] == ["StopLoss.StopLoss", "ProfitTarget.ProfitTarget"]

    def test_indicator_min_max_step(self, sqb_file: Path):
        sqb = parse_sqb(sqb_file)
        atr = next(b for b in sqb.building_blocks if b.key == "Indicators.ATR")
        assert atr.indicator_min == "0"
        assert atr.indicator_max == "500"
        assert atr.indicator_step == "0.5"

    def test_params_preserve_attributes(self, sqb_file: Path):
        """Los params deben conservar generation/minValue/maxValue/step, no solo el texto."""
        sqb = parse_sqb(sqb_file)
        rsi = next(b for b in sqb.building_blocks if b.key == "RSIFalling")
        params = {p["key"]: p for p in rsi.generated.params}
        assert params["#Period#"]["minValue"] == "7"
        assert params["#Period#"]["maxValue"] == "50"
        assert params["#Chart#"]["type"] == "data"

    def test_predefined_sets_parsed_with_params(self, sqb_file: Path):
        sqb = parse_sqb(sqb_file)
        rsi = next(b for b in sqb.building_blocks if b.key == "RSIFalling")
        assert len(rsi.predefined.sets) == 1
        set1 = rsi.predefined.sets[0]
        assert set1["name"] == "Default set 1"
        assert set1["params"][0]["defaultValue"] == "14"

    def test_summary_shows_effective_params(self, sqb_file: Path):
        """El resumen debe exponer valores efectivos de los parámetros."""
        sqb = parse_sqb(sqb_file)
        summary = get_block_summary(sqb)
        rsi_info = next(
            b for b in summary["by_category"]["signals"] if b["key"] == "RSIFalling"
        )
        assert rsi_info["params"]["#Period#"] == "7..50"  # rango (no hay fixed en Generated)
        assert rsi_info["predefined_sets"] == 1

    def test_summary_counts(self, sqb_file: Path):
        sqb = parse_sqb(sqb_file)
        summary = get_block_summary(sqb)
        assert summary["total_blocks"] == 5
        assert summary["active_blocks"] == 0  # todos use=false en el fixture
        assert set(summary["by_category"].keys()) == {"signals", "indicators", "stopLimitBlocks"}

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            parse_sqb(tmp_path / "no_existe.sqb")

    def test_non_zip_raises(self, tmp_path: Path):
        bad = tmp_path / "malo.sqb"
        bad.write_text("no soy un zip")
        with pytest.raises(zipfile.BadZipFile):
            parse_sqb(bad)


# === Tests del builder ===

class TestSqbBuilder:
    def test_load_template_and_list(self, sqb_file: Path):
        root = load_sqb_template(sqb_file)
        keys = list_blocks(root)
        assert "RSIFalling" in keys
        assert len(keys) == 5

    def test_list_blocks_by_category(self, sqb_file: Path):
        root = load_sqb_template(sqb_file)
        assert list_blocks(root, category="signals") == ["RSIFalling", "IsDowntrend"]

    def test_build_activates_selected_blocks(self, sqb_file: Path, tmp_path: Path):
        out = tmp_path / "recomendado.sqb"
        report = build_recommended_sqb(
            template_path=sqb_file,
            output_path=out,
            use_signals=["RSIFalling"],
            use_indicators=["Indicators.ATR"],
            use_stops=["Stop/Limit Price Ranges.ATR"],
            use_order_types=["EnterAtStop"],
            use_exit_types=["StopLoss.StopLoss"],
        )
        assert report["activated"]["signals"] == ["RSIFalling"]
        assert report["activated"]["indicators"] == ["Indicators.ATR"]
        assert report["activated"]["stopLimitBlocks"] == ["Stop/Limit Price Ranges.ATR"]
        assert report["not_found"] == {"signals": [], "indicators": [], "stopLimitBlocks": []}
        assert out.exists()

        # El archivo generado debe preservar TODOS los bloques y marcar solo los elegidos
        sqb = parse_sqb(out)
        assert len(sqb.building_blocks) == 5
        active = {b.key for b in sqb.building_blocks if b.use}
        assert active == {"RSIFalling", "Indicators.ATR", "Stop/Limit Price Ranges.ATR"}

    def test_build_preserves_param_signature(self, sqb_file: Path, tmp_path: Path):
        """Crítico: al activar un bloque, su firma de parámetros debe quedar intacta."""
        out = tmp_path / "rec.sqb"
        build_recommended_sqb(
            template_path=sqb_file,
            output_path=out,
            use_signals=["RSIFalling"],
        )
        sqb = parse_sqb(out)
        rsi = next(b for b in sqb.building_blocks if b.key == "RSIFalling")
        assert rsi.use is True
        keys = [p["key"] for p in rsi.generated.params]
        assert keys == ["#Chart#", "#ComputedFrom#", "#Period#", "#Shift#"]

    def test_build_reports_not_found(self, sqb_file: Path, tmp_path: Path):
        report = build_recommended_sqb(
            template_path=sqb_file,
            output_path=tmp_path / "x.sqb",
            use_signals=["RSIFalling", "NoExisteEstaSeñal"],
        )
        assert report["not_found"]["signals"] == ["NoExisteEstaSeñal"]

    def test_build_disable_rest(self, sqb_file: Path, tmp_path: Path):
        """Categorías especificadas: se desactivan sus no elegidos. Las no
        especificadas (None) quedan intactas."""
        out = tmp_path / "rest.sqb"
        report = build_recommended_sqb(
            template_path=sqb_file,
            output_path=out,
            use_signals=["RSIFalling"],
            disable_rest=True,
        )
        # Solo 'signals' fue especificada → se desactiva IsDowntrend (el otro signal)
        assert report["deactivated"] == 1
        sqb = parse_sqb(out)
        active = {b.key for b in sqb.building_blocks if b.use}
        assert active == {"RSIFalling"}

    def test_unspecified_category_left_untouched(self, sqb_file: Path, tmp_path: Path):
        """Un grupo no especificado (None) NO debe desactivarse."""
        out = tmp_path / "keep.sqb"
        build_recommended_sqb(
            template_path=sqb_file,
            output_path=out,
            use_signals=["RSIFalling"],
            # indicators / stops / order_types / exit_types → None (no tocar)
        )
        sqb = parse_sqb(out)
        # OrderTypes y ExitTypes del template siguen con su valor original (use=false en el fixture)
        assert len(sqb.order_types) == 2
        # Los indicadores conservan su estado original
        atr = next(b for b in sqb.building_blocks if b.key == "Indicators.ATR")
        assert atr.use is False

    def test_explicit_empty_list_disables_all(self, sqb_file: Path, tmp_path: Path):
        """Una lista vacía explícita ([]) sí desactiva todo el grupo."""
        out = tmp_path / "empty.sqb"
        build_recommended_sqb(
            template_path=sqb_file,
            output_path=out,
            use_signals=["RSIFalling"],
            use_order_types=[],   # explícito: desactivar todos
        )
        sqb = parse_sqb(out)
        assert all(b.use is False for b in sqb.order_types)

    def test_get_block_definition(self, sqb_file: Path):
        d = get_block_definition(sqb_file, "RSIFalling")
        assert d["category"] == "signals"
        assert [p["key"] for p in d["params"]] == ["#Chart#", "#ComputedFrom#", "#Period#", "#Shift#"]
        assert d["predefined_sets"] == 1
        assert d["example_defaults"]["#Period#"] == "14"

    def test_get_block_definition_missing(self, sqb_file: Path):
        assert get_block_definition(sqb_file, "NoExiste") is None

    def test_dump_catalog(self, sqb_file: Path):
        catalog = dump_catalog(sqb_file)
        assert len(catalog) == 5
        signals = dump_catalog(sqb_file, category="signals")
        assert {b["key"] for b in signals} == {"RSIFalling", "IsDowntrend"}


# === Tests de validación previa ===

class TestValidateSelection:
    def test_all_valid(self, sqb_file: Path):
        issues = validate_selection(
            sqb_file,
            signals=["RSIFalling", "IsDowntrend"],
            indicators=["Indicators.ATR"],
            stops=["Stop/Limit Price Ranges.ATR"],
        )
        assert issues["ok"] is True
        assert issues["errors"] == []
        assert issues["valid"]["signals"] == ["IsDowntrend", "RSIFalling"]

    def test_invalid_with_suggestion(self, sqb_file: Path):
        issues = validate_selection(sqb_file, signals=["RSIFallng"])  # typo
        assert issues["ok"] is False
        assert len(issues["errors"]) == 1
        cat, name, suggestion = issues["errors"][0]
        assert cat == "signals"
        assert name == "RSIFallng"
        assert suggestion == "RSIFalling"

    def test_invalid_without_suggestion(self, sqb_file: Path):
        issues = validate_selection(sqb_file, signals=["CompletamenteOtraCosa"])
        cat, name, suggestion = issues["errors"][0]
        assert suggestion is None

    def test_order_and_exit_types_validated(self, sqb_file: Path):
        issues = validate_selection(
            sqb_file,
            order_types=["EnterAtStop"],
            exit_types=["StopLoss.StopLoss", "NoExiste"],
        )
        assert issues["ok"] is False
        assert issues["errors"][0][0] == "exitTypes"

    def test_strict_build_aborts(self, sqb_file: Path, tmp_path: Path):
        out = tmp_path / "no.sqb"
        with pytest.raises(ValueError, match="RSIFallng"):
            build_recommended_sqb(
                template_path=sqb_file,
                output_path=out,
                use_signals=["RSIFallng"],
                strict=True,
            )
        assert not out.exists()  # no debe escribir nada


# === Tests de diff ===

class TestDiffSqb:
    def test_diff_detects_activated_and_deactivated(self, sqb_file: Path, tmp_path: Path):
        new = tmp_path / "nuevo.sqb"
        build_recommended_sqb(
            template_path=sqb_file,
            output_path=new,
            use_signals=["RSIFalling"],          # activa este
            use_indicators=["Indicators.ATR"],   # y este
        )
        d = diff_sqb(sqb_file, new)
        assert d["categories"]["signals"]["activated"] == ["RSIFalling"]
        assert d["categories"]["indicators"]["activated"] == ["Indicators.ATR"]
        assert d["summary"]["blocks_activated"] == 2
        assert d["summary"]["has_changes"] is True

    def test_diff_identical_files(self, sqb_file: Path):
        d = diff_sqb(sqb_file, sqb_file)
        assert d["summary"]["has_changes"] is False
        assert d["summary"]["blocks_activated"] == 0

    def test_diff_deactivation(self, sqb_file: Path, tmp_path: Path):
        # Un .sqb con todo activo
        full = tmp_path / "full.sqb"
        build_recommended_sqb(
            template_path=sqb_file,
            output_path=full,
            use_signals=["RSIFalling", "IsDowntrend"],
            use_indicators=["Indicators.ATR", "Prices.Close"],
            use_stops=["Stop/Limit Price Ranges.ATR"],
        )
        # Y otro que solo mantiene un signal
        reduced = tmp_path / "reduced.sqb"
        build_recommended_sqb(
            template_path=full,
            output_path=reduced,
            use_signals=["RSIFalling"],
        )
        d = diff_sqb(full, reduced)
        assert "IsDowntrend" in d["categories"]["signals"]["deactivated"]
        assert d["categories"]["signals"]["activated"] == []


# === Tests de perfiles ===

class TestProfiles:
    def test_save_and_load_json(self, sqb_file: Path, tmp_path: Path):
        prof_path = tmp_path / "perfil.json"
        save_profile(prof_path, {
            "name": "nas100-shorts",
            "signals": ["RSIFalling", "IsDowntrend"],
            "indicators": ["Indicators.ATR"],
            "stopLimitBlocks": ["Stop/Limit Price Ranges.ATR"],
        })
        loaded = load_profile(prof_path)
        assert loaded["signals"] == ["RSIFalling", "IsDowntrend"]
        assert loaded["indicators"] == ["Indicators.ATR"]
        assert loaded["name"] == "nas100-shorts"
        assert loaded["order_types"] == []  # clave ausente → lista vacía

    def test_load_profile_accepts_comma_string(self, tmp_path: Path):
        p = tmp_path / "p.json"
        p.write_text('{"signals": "RSIFalling, IsDowntrend"}', encoding="utf-8")
        loaded = load_profile(p)
        assert loaded["signals"] == ["RSIFalling", "IsDowntrend"]

    def test_load_profile_missing_file(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_profile(tmp_path / "no.json")

    def test_build_from_profile(self, sqb_file: Path, tmp_path: Path):
        report = build_from_profile(
            template_path=sqb_file,
            profile={
                "signals": ["RSIFalling"],
                "indicators": ["Indicators.ATR"],
            },
            output_path=tmp_path / "from_prof.sqb",
        )
        assert report["activated"]["signals"] == ["RSIFalling"]
        assert report["activated"]["indicators"] == ["Indicators.ATR"]

    def test_build_from_profile_path(self, sqb_file: Path, tmp_path: Path):
        prof = tmp_path / "p.json"
        save_profile(prof, {"signals": ["IsDowntrend"]})
        report = build_from_profile(
            template_path=sqb_file,
            profile=prof,
            output_path=tmp_path / "x.sqb",
        )
        assert report["activated"]["signals"] == ["IsDowntrend"]

    def test_profile_roundtrip_via_sqb(self, sqb_file: Path, tmp_path: Path):
        """Extraer perfil de un .sqb y regenerar otro idéntico en selección."""
        built = tmp_path / "base.sqb"
        build_recommended_sqb(
            template_path=sqb_file,
            output_path=built,
            use_signals=["RSIFalling"],
            use_indicators=["Indicators.ATR"],
            use_order_types=["EnterAtStop"],
        )
        sqb = parse_sqb(built)
        profile = {
            "signals": [b.key for b in sqb.building_blocks if b.use and b.category == "signals"],
            "indicators": [b.key for b in sqb.building_blocks if b.use and b.category == "indicators"],
            "stopLimitBlocks": [b.key for b in sqb.building_blocks if b.use and b.category == "stopLimitBlocks"],
            "order_types": [b.key for b in sqb.order_types if b.use],
            "exit_types": [b.key for b in sqb.exit_types if b.use],
        }
        assert profile["signals"] == ["RSIFalling"]
        assert profile["order_types"] == ["EnterAtStop"]
