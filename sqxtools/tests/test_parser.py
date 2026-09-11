"""Tests para el parser de .cfx."""

import json
import zipfile
from pathlib import Path

import pytest

from sqxtools import parse_cfx
from sqxtools.models import CfxType


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_cfx(tmp_path):
    """Crea un .cfx mínimo válido para pruebas."""
    xml = """<?xml version="1.0"?>
<Task type="Build" name="Test" version="144.0">
  <Settings>
    <Options customSettings="false">
      <BuildTradingOptions>
        <Params>
          <Param key="ExitOnFriday" className="ExitOnFriday">true</Param>
        </Params>
      </BuildTradingOptions>
    </Options>
  </Settings>
  <WhatToBuild>
    <StrategyType type="simple" additionalCharts="2" />
    <MarketSides type="short">
      <EntrySymmetry>false</EntrySymmetry>
      <ExitSymmetry>false</ExitSymmetry>
    </MarketSides>
  </WhatToBuild>
  <Rankings type="never">
    <MaxStrategies>1000</MaxStrategies>
  </Rankings>
</Task>"""
    cfx = tmp_path / "test.cfx"
    with zipfile.ZipFile(cfx, "w") as zf:
        zf.writestr("config.xml", xml)
    return cfx


def test_parse_minimal(sample_cfx):
    cfg = parse_cfx(sample_cfx)
    assert cfg.cfx_type == CfxType.BUILD
    assert cfg.version == "144.0"
    assert cfg.metadata["name"] == "Test"
    assert cfg.settings["options"]["trading_options"][0].key == "ExitOnFriday"
    assert cfg.what_to_build["strategy_type"]["type"] == "simple"
    assert cfg.what_to_build["market_sides"]["type"] == "short"
    assert cfg.rankings["max_strategies"] == "1000"


def test_parse_value_types():
    from sqxtools.parser import _parse_value
    assert _parse_value("true") == (True, "bool")
    assert _parse_value("false") == (False, "bool")
    assert _parse_value("42") == (42, "int")
    assert _parse_value("3.14") == (3.14, "float")
    assert _parse_value("hello") == ("hello", "string")


def test_infer_type():
    from sqxtools.models import CfxType
    from xml.etree.ElementTree import fromstring
    from sqxtools.parser import _infer_cfx_type
    assert _infer_cfx_type(fromstring('<Task type="Retester"/>')) == CfxType.RETESTER
    assert _infer_cfx_type(fromstring('<Task type="Optimizer"/>')) == CfxType.OPTIMIZER


@pytest.mark.skipif(not FIXTURES.exists(), reason="Sin fixtures reales")
def test_parse_real_files():
    """Parsea archivos .cfx reales si existen en tests/fixtures."""
    for cfx in FIXTURES.glob("*.cfx"):
        cfg = parse_cfx(cfx)
        assert cfg.cfx_type != CfxType.UNKNOWN, f"{cfx.name}: tipo no inferido"
        assert cfg.nodes or cfg.settings or cfg.what_to_build, f"{cfx.name}: parseo vacío"
        data = json.dumps(cfg.to_dict(), default=str)
        assert len(data) > 100, f"{cfx.name}: salida JSON muy corta"
