"""Analizador de estrategias — genera resumen legible de un CfxConfig."""

from collections import Counter
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

    # === Trading Options (configuración de trading) ===
    summary["trading_options"] = cfg.settings.get("trading_options", [])
    summary["trading_options_analysis"] = _analyze_trading_options(cfg.settings.get("trading_options", []))

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
        "info": [],
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
    
    # En walk-forward, OOS cubre el 100% del IS porque los rangos son subconjuntos contiguos
    # Eso NO es "buena cobertura" — es simplemente cómo funciona walk-forward
    if len(parsed_ranges) > 1:
        analysis["info"].append(f"Walk-forward: {len(parsed_ranges)} rangos OOS cubren {ratio*100:.0f}% del IS (subconjuntos contiguos).")
    elif ratio < 0.3:
        analysis["issues"].append(f"Cobertura OOS muy baja ({ratio*100:.0f}% de IS). Recomendado: al menos 30-50%.")
    elif ratio < 0.5:
        analysis["warnings"].append(f"Cobertura OOS moderada ({ratio*100:.0f}% de IS). Ideal: 50%+.")
    else:
        analysis["warnings"].append(f"Buena cobertura OOS ({ratio*100:.0f}% de IS).")
    
    # Detectar si OOS = IS (mismo período, sin separación real)
    # NOTA: En StrategyQuant, los rangos OOS son subconjuntos del IS para walk-forward.
    # Es CORRECTO que OOS cubra el 100% del IS si los rangos son subperíodos contiguos.
    # Solo es problemático si hay un solo rango OOS = IS completo (sin walk-forward real).
    if parsed_ranges:
        oos_start = min(r["from"] for r in parsed_ranges)
        oos_end = max(r["to"] for r in parsed_ranges)
        
        # Verificar que los rangos OOS estén DENTRO del IS (no se extiendan más allá)
        oos_beyond_start = (oos_start - date_from).days < -30  # OOS empieza antes que IS
        oos_beyond_end = (oos_end - date_to).days > 30  # OOS termina después que IS
        
        if oos_beyond_start or oos_beyond_end:
            analysis["issues"].append("Los rangos OOS se extienden más allá del período IS. Los rangos OOS deben ser subconjuntos del IS.")
        
        # Detectar si hay un solo rango OOS que cubre todo IS (no es walk-forward)
        if len(parsed_ranges) == 1 and abs((oos_end - oos_start).days - total_days) <= 30:
            analysis["warnings"].append("Solo 1 rango OOS cubriendo todo el IS. Para walk-forward real, use múltiples rangos OOS más pequeños.")
        
        # Verificar que los rangos OOS sean subconjuntos válidos (no todo el IS)
        if len(parsed_ranges) > 1:
            # Múltiples rangos = walk-forward válido
            analysis["info"].append(f"Walk-forward con {len(parsed_ranges)} rangos OOS dentro del IS — configuración correcta.")
        elif len(parsed_ranges) == 1 and abs((oos_end - oos_start).days - total_days) > 30:
            # Un solo rango pero más pequeño que IS = válido pero no walk-forward
            analysis["info"].append("Rango OOS único dentro del IS. Válido, pero múltiples rangos dan más confianza.")
    
    # Detectar si rangos OOS se extienden más allá del IS (problema real)
    # En walk-forward, los rangos OOS son subconjuntos del IS — eso es correcto
    for r in parsed_ranges:
        beyond_start = (date_from - r["from"]).days  # >0 si OOS empieza antes que IS
        beyond_end = (r["to"] - date_to).days  # >0 si OOS termina después que IS
        
        if beyond_start > 30:
            analysis["issues"].append(f"Rango OOS {r['from'].strftime('%Y.%m.%d')} - {r['to'].strftime('%Y.%m.%d')} comienza {beyond_start} días ANTES que el IS.")
        if beyond_end > 30:
            analysis["issues"].append(f"Rango OOS {r['from'].strftime('%Y.%m.%d')} - {r['to'].strftime('%Y.%m.%d')} termina {beyond_end} días DESPUÉS que el IS.")
    
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


def _analyze_trading_options(trading_options: list[dict]) -> dict[str, Any]:
    """Analiza los parámetros de trading_options y detecta problemas."""
    opts = {o["key"]: o["value"] for o in trading_options}
    
    analysis: dict[str, Any] = {
        "raw": opts,
        "issues": [],
        "warnings": [],
        "info": [],
    }
    
    # Time Range
    limit_time = opts.get("LimitTimeRange", False)
    time_from = opts.get("SignalTimeRangeFrom", 0)
    time_to = opts.get("SignalTimeRangeTo", 0)
    
    if limit_time:
        from_h = time_from // 3600
        from_m = (time_from % 3600) // 60
        to_h = time_to // 3600
        to_m = (time_to % 3600) // 60
        analysis["info"].append(f"Time Range habilitado: {from_h:02d}:{from_m:02d} - {to_h:02d}:{to_m:02d}")
        
        # Evaluar si el rango es muy corto o muy largo
        range_hours = (time_to - time_from) / 3600
        if range_hours < 4:
            analysis["warnings"].append(f"Time Range muy corto ({range_hours:.1f}h). Podría limitar demasiado las oportunidades.")
        elif range_hours > 12:
            analysis["warnings"].append(f"Time Range muy largo ({range_hours:.1f}h). Incluye horas de baja liquidez.")
        
        # Si el rango incluye la apertura de Londres (8:00-9:00) o Nueva York (13:00-14:00)
        if time_from <= 28800 and time_to >= 32400:
            analysis["info"].append("Incluye apertura de Londres (8:00-9:00 UTC) — alta volatilidad.")
        if time_from <= 46800 and time_to >= 50400:
            analysis["info"].append("Incluye apertura de NY (13:00-14:00 UTC) — alta volatilidad.")
    else:
        if time_from != 0 or time_to != 0:
            analysis["warnings"].append(f"SignalTimeRangeFrom={time_from}/To={time_to} configurados pero LimitTimeRange=false (no tienen efecto).")
    
    # Exit on Friday
    exit_friday = opts.get("ExitOnFriday", False)
    friday_time = opts.get("FridayExitTime", 0)
    if exit_friday:
        h = friday_time // 3600
        m = (friday_time % 3600) // 60
        analysis["info"].append(f"Exit On Friday habilitado: {h:02d}:{m:02d} UTC")
        if friday_time > 72000:  # Después de las 20:00
            analysis["warnings"].append("Exit On Friday tarde (después 20:00 UTC) — puede mantener posiciones overnight.")
    else:
        analysis["info"].append("Exit On Friday desactivado — posiciones pueden mantenerse overnight hasta el viernes.")
    
    # DontTradeOnWeekends
    dont_weekend = opts.get("DontTradeOnWeekends", False)
    if not dont_weekend:
        analysis["warnings"].append("DontTradeOnWeekends=false — se permite operar fines de semana (gap risk).")
    else:
        friday_close = opts.get("FridayCloseTime", 0)
        sunday_open = opts.get("SundayOpenTime", 0)
        fc_h = friday_close // 3600
        so_h = sunday_open // 3600
        analysis["info"].append(f"No operar fines de semana. Viernes cierre: {fc_h:02d}:00, Domingo apertura: {so_h:02d}:00 UTC")
    
    # Exit at End of Day
    exit_eod = opts.get("ExitAtEndOfDay", False)
    eod_time = opts.get("EODExitTime", 0)
    if exit_eod:
        h = eod_time // 3600
        m = (eod_time % 3600) // 60
        analysis["info"].append(f"Exit EOD: {h:02d}:{m:02d} UTC")
    else:
        analysis["info"].append("Exit EOD desactivado — posiciones pueden mantenerse de un día a otro.")
    
    # Max Trades Per Day
    max_trades = opts.get("MaxTradesPerDay", 0)
    if max_trades == 0:
        analysis["warnings"].append("MaxTradesPerDay=0 (sin límite). Riesgo de overtrading en sesiones volátiles.")
    elif max_trades > 10:
        analysis["warnings"].append(f"MaxTradesPerDay={max_trades} — bastante alto, puede generar overtrading.")
    else:
        analysis["info"].append(f"MaxTradesPerDay={max_trades}")
    
    # Min/Max SL/PT en pips (límites duros de trading options, distintos de los
    # rangos de SL/PT que genera el builder en SLPTOptions)
    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    min_sl = _num(opts.get("MinimumSL", 0))
    max_sl = _num(opts.get("MaximumSL", 0))
    min_pt = _num(opts.get("MinimumPT", 0))
    max_pt = _num(opts.get("MaximumPT", 0))

    if min_sl == 0 and max_sl == 0 and min_pt == 0 and max_pt == 0:
        analysis["warnings"].append(
            "Sin límites duros Min/Max SL/PT en trading options — el builder puede "
            "elegir SL/PT extremos aunque los rangos de SLPTOptions sean razonables."
        )
    else:
        if min_sl > 0:
            analysis["info"].append(f"Límite MinSL={min_sl:g} pips")
        if max_sl > 0:
            analysis["info"].append(f"Límite MaxSL={max_sl:g} pips")
        if min_pt > 0:
            analysis["info"].append(f"Límite MinPT={min_pt:g} pips")
        if max_pt > 0:
            analysis["info"].append(f"Límite MaxPT={max_pt:g} pips")

    # Session (filtro de sesión predefinida, independiente del time range)
    session = opts.get("Session", "No Session")
    if session == "No Session":
        if limit_time:
            analysis["info"].append(
                "Sin sesión predefinida, pero el filtro horario está activo "
                "(el rango de horas sí limita las entradas)."
            )
        else:
            analysis["info"].append("Sin filtro de sesión ni horario — opera 24h.")
    else:
        analysis["info"].append(f"Session: {session}")
    
    # Picker Max Open Positions
    max_short = opts.get("PickerMaxOpenPositionsShort", 0)
    max_long = opts.get("PickerMaxOpenPositionsLong", 0)
    if max_short > 5:
        analysis["warnings"].append(f"PickerMaxOpenPositionsShort={max_short} — muchas posiciones cortas simultáneas (riesgo de correlación).")
    if max_long > 5:
        analysis["warnings"].append(f"PickerMaxOpenPositionsLong={max_long} — muchas posiciones largas simultáneas.")
    analysis["info"].append(f"Max posiciones: Long={max_long}, Short={max_short}")
    
    # Realistic Gaps Handling
    gaps = opts.get("RealisticGapsHandling", False)
    if gaps:
        analysis["info"].append("RealisticGapsHandling=true — gaps se manejan realistamente.")
    else:
        analysis["warnings"].append("RealisticGapsHandling=false — los gaps pueden no reflejarse en backtest (overoptimista).")
    
    # Max Distance From Market
    max_dist = opts.get("MaxDistanceFromMarket", False)
    max_dist_pct = opts.get("MaxDistancePct", 0)
    if max_dist and max_dist_pct > 0:
        analysis["info"].append(f"MaxDistanceFromMarket={max_dist_pct}%")
    
    # Reserved Bars
    reserved = opts.get("ReservedBars", 0)
    if reserved > 0:
        analysis["info"].append(f"ReservedBars={reserved}")
    
    return analysis


def active_blocks_only(cfg: CfxConfig) -> list[dict]:
    """Devuelve solo los bloques activos (use=true)."""
    return [b for b in cfg.blocks.get("building_blocks", []) if b.get("use")]


def blocks_by_category(cfg: CfxConfig, category: str, active_only: bool = True) -> list[dict]:
    """Filtra bloques por categoría."""
    blocks = cfg.blocks.get("building_blocks", [])
    if active_only:
        blocks = [b for b in blocks if b.get("use")]
    return [b for b in blocks if b.get("category") == category]
