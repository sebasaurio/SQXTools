"""Tests para el comparador con fixtures reales."""

import json
from pathlib import Path

import pytest

from sqxtools import parse_cfx, compare_configs, summarize

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.mark.skipif(not FIXTURES.exists(), reason="Sin fixtures reales")
class TestRealFiles:
    """Tests contra archivos .cfx reales."""

    def test_parse_build1(self):
        cfg = parse_cfx(FIXTURES / "Build strategies 1.cfx")
        assert cfg.cfx_type.value == "build"
        assert cfg.version == "144.2938"
        assert len(cfg.blocks["building_blocks"]) == 524
        active = sum(1 for b in cfg.blocks["building_blocks"] if b["use"])
        assert active == 110

    def test_parse_build2(self):
        cfg = parse_cfx(FIXTURES / "Build strategies 1 _ 2.cfx")
        assert cfg.cfx_type.value == "build"
        assert len(cfg.blocks["building_blocks"]) == 524
        active = sum(1 for b in cfg.blocks["building_blocks"] if b["use"])
        assert active == 72

    def test_compare_builds(self):
        cfg1 = parse_cfx(FIXTURES / "Build strategies 1.cfx")
        cfg2 = parse_cfx(FIXTURES / "Build strategies 1 _ 2.cfx")
        diff = compare_configs(cfg1, cfg2)
        assert diff["blocks"]["active1"] == 110
        assert diff["blocks"]["active2"] == 72
        assert diff["blocks"]["common"] == 69
        assert len(diff["blocks"]["only_in_file1"]) == 41
        assert len(diff["blocks"]["only_in_file2"]) == 3
        assert "slpt_options_diff" in diff
        assert "MaxSLATRMultiple" in diff["slpt_options_diff"]

    def test_summarize_build1(self):
        cfg = parse_cfx(FIXTURES / "Build strategies 1.cfx")
        s = summarize(cfg)
        assert s["blocks_summary"]["total"] == 524
        assert s["blocks_summary"]["active"] == 110
        assert s["data"]["num_setups"] == 1
        assert s["data"]["out_of_sample_ranges"] == 4
        assert s["rankings"]["num_active_conditions"] == 4
        assert s["rankings"]["num_conditions"] == 11
        assert "stopLimitBlocks" in s["categories"]
        assert "indicators" in s["categories"]
        assert "signals" in s["categories"]

    def test_json_output_build1(self):
        cfg = parse_cfx(FIXTURES / "Build strategies 1.cfx")
        d = cfg.to_dict()
        assert len(json.dumps(d, default=str)) > 100000
        assert d["filename"] == "Build strategies 1.cfx"
        assert d["cfx_type"] == "build"
