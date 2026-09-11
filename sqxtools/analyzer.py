"""Analizador de estrategias — genera resumen legible de un CfxConfig."""

from collections import Counter
from pathlib import Path
from typing import Any

from .models import CfxConfig


def summarize(cfg: CfxConfig) -> dict[str, Any]:
    """Genera un resumen ejecutivo de la estrategia."""
    summary: dict[str, Any] = {
        "filename": cfg.filename,
        "type": cfg.cfx_type.value,
        "version": cfg.version,
        "metadata": cfg.metadata,
    }

    # === Building Blocks activos ===
    blocks = cfg.blocks.get("building_blocks", [])
    active_blocks = [b for b in blocks if b.get("use")]
    inactive_blocks = [b for b in blocks if not b.get("use")]

    summary["blocks_summary"] = {
        "total": len(blocks),
        "active": len(active_blocks),
        "inactive": len(inactive_blocks),
    }

    # === Categorías de bloques activos ===
    categories = Counter(b.get("category", "") for b in active_blocks)
    summary["categories"] = dict(categories.most_common())

    # === Bloques activos por categoría ===
    by_category: dict[str, list[str]] = {}
    for b in active_blocks:
        cat = b.get("category", "uncategorized")
        by_category.setdefault(cat, []).append(b["key"])
    summary["active_by_category"] = by_category

    # === Entry/Exit Rules detectadas (desde WhatToBuild + Blocks) ===
    wtj = cfg.what_to_build
    if wtj:
        summary["strategy_type"] = wtj.get("strategy_type", {}).get("type", "")
        summary["market_sides"] = wtj.get("market_sides", {}).get("type", "")
        summary["additional_charts"] = wtj.get("strategy_type", {}).get("additionalCharts", "")

        # SL/PT
        slpt = wtj.get("slpt_options", {})
        summary["slpt"] = {
            "sl_required": slpt.get("SLRequired", False),
            "pt_required": slpt.get("PTRequired", False),
            "sl_atr_based": slpt.get("SLATR", False),
            "pt_atr_based": slpt.get("PTATR", False),
            "sl_fixed_pips": slpt.get("SLFixedPips", False),
            "pt_fixed_pips": slpt.get("PTFixedPips", False),
        }

        # Build mode
        bm = wtj.get("build_mode", {})
        summary["build_mode"] = {
            "type": bm.get("generationType", ""),
            "population_size": bm.get("PopulationSize", ""),
            "max_generations": bm.get("MaxGenerations", ""),
            "crossover_prob": bm.get("CrossoverProbability", ""),
            "mutation_prob": bm.get("MutationProbability", ""),
            "islands": bm.get("Islands", ""),
        }

    # === Indicadores/parametros usados ===
    indicators = _extract_indicators(active_blocks)
    summary["indicators"] = indicators

    # === Data / Setups ===
    data = cfg.data
    if data:
        setups = data.get("setups", [])
        summary["data"] = {
            "num_setups": len(setups),
            "charts": [],
            "out_of_sample_ranges": len(data.get("out_of_sample", {}).get("ranges", [])),
        }
        for s in setups:
            for chart in s.get("charts", []):
                summary["data"]["charts"].append({
                    "symbol": chart.get("symbol", ""),
                    "timeframe": chart.get("timeframe", ""),
                    "spread": chart.get("spread", ""),
                })
            summary["data"]["date_range"] = {
                "from": s.get("dateFrom", ""),
                "to": s.get("dateTo", ""),
            }

    # === Rankings / Filtros de calidad ===
    rankings = cfg.rankings
    if rankings:
        summary["rankings"] = {
            "type": rankings.get("type", ""),
            "max_strategies": rankings.get("max_strategies", ""),
            "fitness_criteria": rankings.get("fitness_criteria", {}).get("type", ""),
            "conditions_type": rankings.get("conditions_type", ""),
        }
        conds = rankings.get("conditions", [])
        active_conds = [c for c in conds if c.get("use")]
        summary["rankings"]["num_conditions"] = len(conds)
        summary["rankings"]["num_active_conditions"] = len(active_conds)
        summary["rankings"]["active_filters"] = [
            {
                "left": c.get("left_side", {}).get("column", {}).get("column", ""),
                "comparator": c.get("comparator", ""),
                "right": c.get("right_side", {}).get("numeric", ""),
            }
            for c in active_conds
        ]

    # === Cross Checks ===
    cc = cfg.cross_checks
    if cc:
        enabled_checks = []
        for key in ("RetestOnAdditionalMarkets", "WalkForwardOptimization",
                     "RetestWithHigherPrecision", "MonteCarloRetest",
                     "WalkForwardMatrix", "MonteCarloManipulation",
                     "OptProfileSysParamPermutation", "WhatIf"):
            if cc.get(key, {}).get("use"):
                enabled_checks.append(key)
        summary["cross_checks"] = {
            "use": cc.get("use", False),
            "evaluate_all": cc.get("evaluateAll", False),
            "enabled": enabled_checks,
        }

    # === Order/Exit types activos ===
    order_types = cfg.blocks.get("order_types", [])
    exit_types = cfg.blocks.get("exit_types", [])
    summary["order_types"] = [{"key": b["key"], "use": b["use"]} for b in order_types]
    summary["exit_types"] = [{"key": b["key"], "use": b["use"], "probability": b.get("probability", "")} for b in exit_types]

    # === Resources ===
    res = cfg.resources
    if res:
        summary["resources"] = {
            "symbols": [s["name"] for s in res.get("symbols", [])],
            "brokers": [b["name"] for b in res.get("brokers", [])],
        }

    return summary


def _extract_indicators(active_blocks: list[dict]) -> list[dict]:
    """Extrae indicadores únicos de los bloques activos."""
    indicators = []
    seen = set()
    for b in active_blocks:
        name = b["key"]
        if name in seen:
            continue
        seen.add(name)
        params = b.get("params", [])
        param_summary = []
        for p in params:
            if p.get("paramType") != "null" and p.get("value") not in ("", None):
                param_summary.append({
                    "key": p["key"],
                    "name": p["name"],
                    "value": p["value"],
                })
        indicators.append({
            "name": name,
            "category": b.get("category", ""),
            "params": param_summary,
        })
    return indicators


def active_blocks_only(cfg: CfxConfig) -> list[dict]:
    """Devuelve solo los bloques activos (use=true)."""
    return [b for b in cfg.blocks.get("building_blocks", []) if b.get("use")]


def blocks_by_category(cfg: CfxConfig, category: str, active_only: bool = True) -> list[dict]:
    """Filtra bloques por categoría."""
    blocks = cfg.blocks.get("building_blocks", [])
    if active_only:
        blocks = [b for b in blocks if b.get("use")]
    return [b for b in blocks if b.get("category") == category]
