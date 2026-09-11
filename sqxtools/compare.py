"""Comparador de configuraciones .cfx — detecta diferencias entre dos builds."""

from typing import Any

from .models import CfxConfig


def compare_configs(cfg1: CfxConfig, cfg2: CfxConfig) -> dict[str, Any]:
    """Compara dos CfxConfig y devuelve diferencias estructuradas."""
    diff: dict[str, Any] = {
        "file1": cfg1.filename,
        "file2": cfg2.filename,
        "summary": {
            "type_match": cfg1.cfx_type == cfg2.cfx_type,
            "version_match": cfg1.version == cfg2.version,
            "type1": cfg1.cfx_type.value,
            "type2": cfg2.cfx_type.value,
        },
    }

    # === Comparar bloques activos ===
    blocks1 = cfg1.blocks.get("building_blocks", [])
    blocks2 = cfg2.blocks.get("building_blocks", [])

    active1 = {b["key"] for b in blocks1 if b.get("use")}
    active2 = {b["key"] for b in blocks2 if b.get("use")}

    only_in_1 = sorted(active1 - active2)
    only_in_2 = sorted(active2 - active1)
    common = sorted(active1 & active2)

    diff["blocks"] = {
        "total1": len(blocks1),
        "total2": len(blocks2),
        "active1": len(active1),
        "active2": len(active2),
        "common": len(common),
        "only_in_file1": only_in_1,
        "only_in_file2": only_in_2,
        "common_blocks": common,
    }

    # === Comparar categorías ===
    cats1 = {}
    cats2 = {}
    for b in blocks1:
        if b.get("use"):
            cats1[b.get("category", "")] = cats1.get(b.get("category", ""), 0) + 1
    for b in blocks2:
        if b.get("use"):
            cats2[b.get("category", "")] = cats2.get(b.get("category", ""), 0) + 1
    all_cats = set(cats1.keys()) | set(cats2.keys())
    diff["categories"] = {
        "file1": cats1,
        "file2": cats2,
        "differences": {c: cats1.get(c, 0) - cats2.get(c, 0) for c in all_cats if cats1.get(c, 0) != cats2.get(c, 0)},
    }

    # === Comparar SLPTOptions ===
    slpt1 = cfg1.what_to_build.get("slpt_options", {})
    slpt2 = cfg2.what_to_build.get("slpt_options", {})
    if slpt1 or slpt2:
        slpt_diff = {}
        keys = set(slpt1.keys()) | set(slpt2.keys())
        for k in sorted(keys):
            v1 = slpt1.get(k, "N/A")
            v2 = slpt2.get(k, "N/A")
            if v1 != v2:
                slpt_diff[k] = {"file1": v1, "file2": v2}
        diff["slpt_options_diff"] = slpt_diff

    # === Comparar Data / Setups ===
    setups1 = cfg1.data.get("setups", [])
    setups2 = cfg2.data.get("setups", [])
    charts1 = [c["symbol"] for s in setups1 for c in s.get("charts", [])]
    charts2 = [c["symbol"] for s in setups2 for c in s.get("charts", [])]
    diff["data"] = {
        "setups1": len(setups1),
        "setups2": len(setups2),
        "charts1": charts1,
        "charts2": charts2,
        "charts_match": charts1 == charts2,
    }

    # === Comparar Rankings ===
    r1 = cfg1.rankings
    r2 = cfg2.rankings
    if r1 and r2:
        rank_diff = {}
        for k in ("type", "max_strategies", "fitness_criteria"):
            v1 = r1.get(k, "")
            v2 = r2.get(k, "")
            if v1 != v2:
                rank_diff[k] = {"file1": v1, "file2": v2}
        diff["rankings_diff"] = rank_diff

    # === Comparar BuildMode ===
    bm1 = cfg1.what_to_build.get("build_mode", {})
    bm2 = cfg2.what_to_build.get("build_mode", {})
    if bm1 and bm2:
        bm_diff = {}
        for k in ("generationType", "PopulationSize", "MaxGenerations", "CrossoverProbability", "MutationProbability"):
            v1 = bm1.get(k, "")
            v2 = bm2.get(k, "")
            if v1 != v2:
                bm_diff[k] = {"file1": v1, "file2": v2}
        diff["build_mode_diff"] = bm_diff

    # === Comparar order/exit types ===
    ot1 = {b["key"]: b["use"] for b in cfg1.blocks.get("order_types", [])}
    ot2 = {b["key"]: b["use"] for b in cfg2.blocks.get("order_types", [])}
    diff["order_types"] = {
        "file1": ot1,
        "file2": ot2,
    }

    et1 = {b["key"]: b["use"] for b in cfg1.blocks.get("exit_types", [])}
    et2 = {b["key"]: b["use"] for b in cfg2.blocks.get("exit_types", [])}
    diff["exit_types"] = {
        "file1": et1,
        "file2": et2,
    }

    return diff
