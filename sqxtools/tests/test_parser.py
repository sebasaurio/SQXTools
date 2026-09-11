"""Tests para el parser, analyzer y comparator de .cfx."""

import json
import zipfile
from pathlib import Path

import pytest

from sqxtools import (
    parse_cfx,
    summarize,
    active_blocks_only,
    blocks_by_category,
    compare_configs,
    to_yaml,
    to_markdown,
    to_json,
)
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
    <WhatToBuild>
      <StrategyType type="simple" additionalCharts="2" />
      <MarketSides type="short">
        <EntrySymmetry>false</EntrySymmetry>
        <ExitSymmetry>false</ExitSymmetry>
      </MarketSides>
      <SLPTOptions>
        <SLRequired>true</SLRequired>
        <PTRequired>true</PTRequired>
      </SLPTOptions>
    </WhatToBuild>
    <Rankings type="never">
      <MaxStrategies>1000</MaxStrategies>
    </Rankings>
    <Blocks>
      <BuildingBlocks>
        <Block key="TestBlock" weight="1" use="true" category="signals">
          <Generated weight="1">
            <Param key="#Period#" name="Period" type="int" paramType="null">14</Param>
          </Generated>
          <Predefined changed="false" />
        </Block>
        <Block key="InactiveBlock" weight="1" use="false" category="signals">
          <Generated weight="1" />
          <Predefined changed="false" />
        </Block>
      </BuildingBlocks>
    </Blocks>
  </Settings>
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
    assert cfg.settings["trading_options"][0]["key"] == "ExitOnFriday"
    assert cfg.what_to_build["strategy_type"]["type"] == "simple"
    assert cfg.what_to_build["market_sides"]["type"] == "short"
    assert cfg.rankings["max_strategies"] == "1000"


def test_blocks(sample_cfx):
    cfg = parse_cfx(sample_cfx)
    blocks = cfg.blocks["building_blocks"]
    assert len(blocks) == 2
    assert blocks[0]["key"] == "TestBlock"
    assert blocks[0]["use"] is True
    assert blocks[1]["use"] is False


def test_summarize(sample_cfx):
    cfg = parse_cfx(sample_cfx)
    s = summarize(cfg)
    assert s["type"] == "build"
    assert s["blocks_summary"]["total"] == 2
    assert s["blocks_summary"]["active"] == 1
    assert "signals" in s["categories"]


def test_active_blocks_only(sample_cfx):
    cfg = parse_cfx(sample_cfx)
    active = active_blocks_only(cfg)
    assert len(active) == 1
    assert active[0]["key"] == "TestBlock"


def test_blocks_by_category(sample_cfx):
    cfg = parse_cfx(sample_cfx)
    sig = blocks_by_category(cfg, "signals", active_only=True)
    assert len(sig) == 1


def test_serializers(sample_cfx):
    cfg = parse_cfx(sample_cfx)
    j = to_json(cfg)
    assert "Test" in j
    m = to_markdown(cfg)
    assert "Build" in m
    y = to_yaml(cfg)
    assert "filename" in y


def test_compare(sample_cfx, tmp_path):
    xml2 = """<?xml version="1.0"?>
<Task type="Build" name="Test2" version="144.0">
  <Settings>
    <Blocks>
      <BuildingBlocks>
        <Block key="TestBlock" weight="1" use="false" category="signals">
          <Generated weight="1" />
          <Predefined changed="false" />
        </Block>
        <Block key="NewBlock" weight="1" use="true" category="indicators">
          <Generated weight="1" />
          <Predefined changed="false" />
        </Block>
      </BuildingBlocks>
    </Blocks>
  </Settings>
</Task>"""
    cfx2 = tmp_path / "test2.cfx"
    with zipfile.ZipFile(cfx2, "w") as zf:
        zf.writestr("config.xml", xml2)
    cfg2 = parse_cfx(cfx2)
    diff = compare_configs(parse_cfx(sample_cfx), cfg2)
    assert diff["blocks"]["only_in_file1"] == ["TestBlock"]
    assert diff["blocks"]["only_in_file2"] == ["NewBlock"]


@pytest.mark.skipif(not FIXTURES.exists(), reason="Sin fixtures reales")
def test_parse_real_files():
    """Parsea archivos .cfx reales si existen en tests/fixtures."""
    for cfx in FIXTURES.glob("*.cfx"):
        cfg = parse_cfx(cfx)
        assert cfg.cfx_type != CfxType.UNKNOWN, f"{cfx.name}: tipo no inferido"
        d = json.dumps(cfg.to_dict(), default=str)
        assert len(d) > 100, f"{cfx.name}: salida JSON muy corta"
        s = summarize(cfg)
        assert s["blocks_summary"]["total"] > 0, f"{cfx.name}: sin bloques"
        assert len(active_blocks_only(cfg)) > 0, f"{cfx.name}: sin bloques activos"


@pytest.mark.skipif(not FIXTURES.exists(), reason="Sin fixtures reales")
def test_compare_real_files():
    """Compara los dos archivos reales."""
    files = list(FIXTURES.glob("*.cfx"))
    if len(files) >= 2:
        cfg1 = parse_cfx(files[0])
        cfg2 = parse_cfx(files[1])
        diff = compare_configs(cfg1, cfg2)
        assert "blocks" in diff
        assert "slpt_options_diff" in diff
        assert "categories" in diff
