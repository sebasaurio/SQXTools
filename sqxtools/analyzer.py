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
        oos = data.get("out_of_sample", {})
        ranges = oos.get("ranges", [])
        
        summary["data"] = {
            "num_setups": len(setups),
            "charts": [],
            "out_of_sample_ranges": len(ranges),
            "out_of_sample": {
                "showGraph": oos.get("showGraph", "true"),
                "ranges": ranges,
            },
        }
        for s in setups:
            for chart in s.get("charts", []):
                summary["data"]["charts"].append({
                    "symbol": chart.get("symbol", ""),
                    "timeframe": chart.get("timeframe", ""),
                    "spread": chart.get("spread", ""),
                })
            # Fechas IS del setup
            summary["data"]["in_sample"] = {
                "dateFrom": s.get("dateFrom", ""),
                "dateTo": s.get("dateTo", ""),
                "testPrecision": s.get("testPrecision", ""),
                "session": s.get("session", ""),
            }
        
        # Análisis de fechas IS vs OOS
        summary["data"]["date_analysis"] = _analyze_dates(s.get("dateFrom", ""), s.get("dateTo", ""), ranges)

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


def _analyze_dates(is_from: str, is_to: str, oos_ranges: list[dict]) -> dict[str, Any]:
    """Analiza las fechas de IS y OOS para detectar problemas."""
    from datetime import datetime
    
    analysis: dict[str, Any] = {
        "in_sample": {"from": is_from, "to": is_to},
        "out_of_sample": oos_ranges,
        "issues": [],
        "warnings": [],
    }
    
    # Parsear fechas
    try:
        date_from = datetime.strptime(is_from, "%Y.%m.%d") if is_from else None
        date_to = datetime.strptime(is_to, "%Y.%m.%d") if is_to else None
    except ValueError:
        analysis["issues"].append("Formato de fecha inválido (esperado: YYYY.MM.DD)")
        return analysis
    
    if not date_from or not date_to:
        analysis["issues"].append("Fechas IS faltantes")
        return analysis
    
    # Duración total del período IS
    total_days = (date_to - date_from).days
    total_years = total_days / 365.25
    analysis["is_total_days"] = total_days
    analysis["is_total_years"] = round(total_years, 2)
    
    # Evaluar si el período IS es suficiente
    if total_years < 3:
        analysis["issues"].append(f"Período IS muy corto ({total_years:.1f} años). Mínimo recomendado: 3 años para robustez.")
    elif total_years < 5:
        analysis["warnings"].append(f"Período IS aceptable ({total_years:.1f} años), pero 5+ años es ideal.")
    else:
        analysis["warnings"].append(f"Período IS bueno ({total_years:.1f} años).")
    
    # Analizar rangos OOS
    if not oos_ranges:
        analysis["issues"].append("No hay rangos OOS definidos. Sin OOS no se puede validar robustez.")
        return analysis
    
    # Parsear rangos OOS
    parsed_ranges = []
    for r in oos_ranges:
        try:
            rf = datetime.strptime(r.get("dateFrom", ""), "%Y.%m.%d")
            rt = datetime.strptime(r.get("dateTo", ""), "%Y.%m.%d")
            parsed_ranges.append({"from": rf, "to": rt, "type": r.get("type", ""), "days": (rt - rf).days})
        except (ValueError, TypeError):
            analysis["issues"].append(f"Rango OOS con fechas inválidas: {r}")
    
    # Calcular cobertura OOS
    oos_days = sum(r["days"] for r in parsed_ranges)
    oos_years = oos_days / 365.25
    analysis["oos_total_days"] = oos_days
    analysis["oos_total_years"] = round(oos_years, 2)
    analysis["oos_coverage_pct"] = round((oos_days / total_days) * 100, 1) if total_days > 0 else 0
    
    # Evaluar ratio IS:OOS
    ratio = oos_days / total_days if total_days > 0 else 0
    analysis["is_oos_ratio"] = f"{ratio:.2f}:1"
    
    if ratio < 0.3:
        analysis["issues"].append(f"Cobertura OOS muy baja ({ratio*100:.0f}% de IS). Recomendado: al menos 30-50%.")
    elif ratio < 0.5:
        analysis["warnings"].append(f"Cobertura OOS moderada ({ratio*100:.0f}% de IS). Ideal: 50%+.")
    else:
        analysis["warnings"].append(f"Buena cobertura OOS ({ratio*100:.0f}% de IS).")
    
    # Detectar si OOS = IS (mismo período, sin separación real)
    if parsed_ranges:
        oos_start = min(r["from"] for r in parsed_ranges)
        oos_end = max(r["to"] for r in parsed_ranges)
        
        # Si OOS cubre prácticamente el mismo período que IS
        if (abs((oos_start - date_from).days) <= 30 and 
            abs((oos_end - date_to).days) <= 30 and
            oos_days >= total_days * 0.9):
            analysis["issues"].append("CRÍTICO: Los rangos OOS cubren prácticamente el MISMO período que el IS. No hay separación real entre IS y OOS — esto invalida la validación. Configure los rangos OOS como subconjuntos del IS o use walk-forward.")
            # Limpiar warnings engañosos
            analysis["warnings"] = [w for w in analysis["warnings"] if "cobertura" not in w.lower() and "buena cantidad" not in w.lower()]
            analysis["warnings"].append("Configure los rangos OOS para que sean subconjuntos del IS (ej. 30-50% del período), no el total.")
    
    # Detectar overlaps entre OOS y IS
    for r in parsed_ranges:
        if r["from"] <= date_to and r["to"] >= date_from:
            # Solo reportar si no ya se detectó el caso OOS=IS
            if not any("CRÍTICO" in i for i in analysis["issues"]):
                analysis["issues"].append(f"Rango OOS {r['from'].strftime('%Y.%m.%d')} - {r['to'].strftime('%Y.%m.%d')} se solapa con IS.")
    
    # Detectar gaps entre rangos OOS
    if len(parsed_ranges) > 1:
        sorted_ranges = sorted(parsed_ranges, key=lambda x: x["from"])
        for i in range(len(sorted_ranges) - 1):
            gap = (sorted_ranges[i+1]["from"] - sorted_ranges[i]["to"]).days
            if gap > 30:
                analysis["warnings"].append(f"Gap de {gap} días entre rangos OOS ({sorted_ranges[i]['to'].strftime('%Y.%m.%d')} -> {sorted_ranges[i+1]['from'].strftime('%Y.%m.%d')}).")
    
    # Evaluar períodos OOS individuales
    for r in parsed_ranges:
        r_years = r["days"] / 365.25
        if r_years < 0.25:
            analysis["warnings"].append(f"Rango OOS muy corto ({r['days']} días). Recomendado: al menos 3 meses por rango.")
    
    # Recomendación de Walk-Forward basada en cantidad de rangos
    num_ranges = len(parsed_ranges)
    analysis["num_oos_ranges"] = num_ranges
    
    if num_ranges == 1:
        analysis["warnings"].append("Solo 1 rango OOS. Walk-forward con múltiples rangos da más confianza.")
    elif num_ranges >= 3:
        analysis["warnings"].append(f"Buena cantidad de rangos OOS ({num_ranges}) para walk-forward.")
    
    return analysis


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
