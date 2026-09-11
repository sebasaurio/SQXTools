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
    dump_catalog,
    get_block_definition,
    list_blocks,
    load_sqb_template,
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
        out = tmp_path / "rest.sqb"
        report = build_recommended_sqb(
            template_path=sqb_file,
            output_path=out,
            use_signals=["RSIFalling"],
            disable_rest=True,
        )
        assert report["deactivated"] == 4  # los otros 4 bloques
        sqb = parse_sqb(out)
        assert sum(1 for b in sqb.building_blocks if b.use) == 1

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
