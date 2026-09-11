"""Edge Analyzer — analiza datos históricos para encontrar ventajas del mercado.

Propuesta de building blocks separada en categorías:
- signals: Señales de entrada (RSIFalling, ADXHigher, etc.)
- indicators: Indicadores de confirmación (Indicators.RSI, Indicators.MACD, etc.)
- stopLimitBlocks: Niveles de stop/target (Stop/Limit Price Levels.RSI, etc.)
"""

import math

import pandas as pd
from typing import Any


# Mapeo de señales propuestas a categorías y parámetros típicos en StrategyQuant

def analyze_market(
    df: pd.DataFrame,
    symbol: str = "USATECHIDX",
    timeframe: str = "H1",
) -> dict[str, Any]:
    """Analiza datos históricos y propone configuración óptima de builder."""
    analysis = {
        "symbol": symbol,
        "timeframe": timeframe,
        "data_info": {},
        "volatility": {},
        "sessions": {},
        "patterns": {},
        "indicators": {},
        "builder_proposal": {},
    }
    
    analysis["data_info"] = {
        "total_bars": len(df),
        "date_from": str(df["timestamp"].iloc[0]) if "timestamp" in df.columns else "N/A",
        "date_to": str(df["timestamp"].iloc[-1]) if "timestamp" in df.columns else "N/A",
        "avg_close": float(df["close"].mean()),
    }
    
    df["returns"] = df["close"].pct_change()
    df["range"] = df["high"] - df["low"]
    df["range_pct"] = (df["high"] - df["low"]) / df["close"] * 100
    
    analysis["volatility"] = {
        "daily_volatility": float(df["returns"].std() * 100),
        "avg_range_pct": float(df["range_pct"].mean()),
        "max_range_pct": float(df["range_pct"].max()),
        "min_range_pct": float(df["range_pct"].min()),
        "atr_14": float(df["range"].rolling(14).mean().iloc[-1]) if len(df) >= 14 else None,
    }
    
    if "timestamp" in df.columns:
        df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
        df["dayofweek"] = pd.to_datetime(df["timestamp"]).dt.dayofweek
        
        hourly_vol = df.groupby("hour")["range_pct"].agg(["mean", "std", "count"])
        hourly_vol.columns = ["avg_range", "std_range", "count"]
        
        top_hours = hourly_vol.nlargest(5, "avg_range")
        analysis["sessions"] = {
            "most_volatile_hours": [
                {"hour": int(h), "avg_range_pct": round(v["avg_range"], 3)}
                for h, v in top_hours.iterrows()
            ],
            "least_volatile_hours": [
                {"hour": int(h), "avg_range_pct": round(v["avg_range"], 3)}
                for h, v in hourly_vol.nsmallest(3, "avg_range").iterrows()
            ],
            "hourly_analysis": _find_best_hours(df),
        }
    
    df["body"] = abs(df["close"] - df["open"])
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["body_pct"] = df["body"] / (df["high"] - df["low"] + 1e-10) * 100
    
    doji = df[df["body_pct"] < 20]
    analysis["patterns"]["doji_pct"] = round(len(doji) / len(df) * 100, 2)
    
    short_wick = df[df["upper_wick"] > df["body"] * 2]
    analysis["patterns"]["short_rejection_pct"] = round(len(short_wick) / len(df) * 100, 2)
    
    long_lower = df[df["lower_wick"] > df["body"] * 2]
    analysis["patterns"]["long_lower_wick_pct"] = round(len(long_lower) / len(df) * 100, 2)
    
    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    
    if len(df) >= 50:
        downtrend = df[df["sma_20"] < df["sma_50"]]
        analysis["patterns"]["downtrend_pct"] = round(len(downtrend) / len(df) * 100, 2)
    else:
        analysis["patterns"]["downtrend_pct"] = None
    
    analysis["indicators"] = _propose_indicators(df, analysis)
    analysis["builder_proposal"] = _propose_builder_config(analysis)
    
    return analysis


def _two_sided_p(t: float) -> float:
    """p-valor aproximado (normal) para un t-stat, sin dependencias externas."""
    return math.erfc(abs(t) / math.sqrt(2))


def _find_best_hours(df: pd.DataFrame) -> dict:
    """Analiza el sesgo direccional y la volatilidad por hora.

    IMPORTANTE — por qué se testea significancia:
    El retorno medio por hora es extremadamente ruidoso. En NAS100 solo ~1 de cada
    24 horas supera el 5% de significancia (exactamente lo esperable por azar), así
    que rankear horas por retorno medio sin test produce "mejores horas" que son
    puro ruido. La volatilidad, en cambio, sí es un patrón robusto y repetible.

    Devuelve:
        {
          "hours": [...],                  # todas las horas con métricas
          "directional_edge": [...],       # horas con sesgo SIGNIFICATIVO (p<0.05)
          "directional_edge_found": bool,
          "most_volatile_hours": [...],    # patrón robusto
          "note": str,
        }
    """
    empty = {
        "hours": [], "directional_edge": [], "directional_edge_found": False,
        "most_volatile_hours": [], "note": "Sin columna 'hour'.",
    }
    if "hour" not in df.columns:
        return empty

    rows = []
    for hour, grp in df.groupby("hour"):
        rets = grp["returns"].dropna()
        n = len(rets)
        if n < 30:
            continue
        mean = float(rets.mean())
        std = float(rets.std()) if n > 1 else 0.0
        t = mean / (std / math.sqrt(n)) if std > 0 else 0.0
        p = _two_sided_p(t)
        rows.append({
            "hour": int(hour),
            "count": n,
            "avg_range_pct": round(float(grp["range_pct"].mean()), 3),
            "avg_return_pct": round(mean * 100, 4),
            "t_stat": round(t, 2),
            "p_value": round(p, 4),
            "significant": bool(p < 0.05),
        })

    if not rows:
        return empty

    rows.sort(key=lambda r: r["hour"])

    # Horas con sesgo direccional real (no ruido)
    directional = [r for r in rows if r["significant"]]

    # Volatilidad: patrón robusto
    most_vol = sorted(rows, key=lambda r: -r["avg_range_pct"])[:5]

    if directional:
        bearish = [r["hour"] for r in directional if r["avg_return_pct"] < 0]
        bullish = [r["hour"] for r in directional if r["avg_return_pct"] >= 0]
        parts = []
        if bearish:
            parts.append(f"favorables para SHORTS: {bearish}")
        if bullish:
            parts.append(f"a EVITAR en shorts (sesgo alcista): {bullish}")
        note = (
            f"{len(directional)} hora(s) con sesgo direccional significativo (p<0.05) — "
            + "; ".join(parts) + ". El resto de las horas no aporta señal direccional."
        )
    else:
        note = (
            "Ninguna hora tiene sesgo direccional significativo: el retorno medio por "
            "hora es ruido. NO filtres el horario por dirección — filtrá por VOLATILIDAD "
            "(excluí las horas muertas) y dejá que las señales hagan el trabajo direccional."
        )

    return {
        "hours": rows,
        "directional_edge": directional,
        "directional_edge_found": bool(directional),
        "most_volatile_hours": most_vol,
        "note": note,
    }


def _propose_indicators(df: pd.DataFrame, analysis: dict) -> dict:
    """Propone indicadores organizados por categoría (signals, indicators, stopLimitBlocks).

    IMPORTANTE: los nombres deben coincidir EXACTAMENTE con los bloques del catálogo
    de StrategyQuant (ver sqb_builder.dump_catalog), porque SQ valida la firma de
    parámetros de cada bloque. Nombres inventados hacen que SQ no marque el bloque.
    """
    proposals = {
        "signals": [],
        "indicators": [],
        "stopLimitBlocks": [],
    }
    
    # === SIGNALS (señales de entrada) ===
    if analysis["patterns"].get("downtrend_pct", 0) > 55:
        proposals["signals"].extend([
            {"name": "SuperTrendDownTrend", "reason": f"Tendencia bajista dominante ({analysis['patterns']['downtrend_pct']}%)"},
            {"name": "IsDowntrend", "reason": "Confirmación de tendencia"},
        ])
    else:
        proposals["signals"].extend([
            {"name": "SuperTrendDownTrend", "reason": "Tendencia general del mercado"},
            {"name": "IsDowntrend", "reason": "Confirmación de tendencia"},
        ])
    
    proposals["signals"].extend([
        {"name": "RSIFalling", "reason": "RSI bajando desde zona alta = entrada más segura para shorts"},
        {"name": "MACDSignalFalling", "reason": "Confirmación de momentum bajista"},
    ])
    
    if analysis["patterns"].get("doji_pct", 0) > 10:
        proposals["signals"].append(
            {"name": "ADXHigher", "reason": f"Alta frecuencia de doji ({analysis['patterns']['doji_pct']}%) — ADX confirma fuerza de tendencia"}
        )
    
    proposals["signals"].extend([
        {"name": "ATRRising", "reason": "Volatilidad creciente = oportunidades de shorts"},
        {"name": "BBUpperFalling", "reason": "Banda superior de BB cayendo = continuación bajista"},
    ])
    
    # === INDICATORS (confirmación) ===
    proposals["indicators"].extend([
        {"name": "Indicators.RSI", "reason": "RSI para confirmar momentum (14 períodos)"},
        {"name": "Indicators.MACD", "reason": "MACD para confirmar cruce bajista"},
        {"name": "Indicators.ATR", "reason": "ATR para medir volatilidad (14 períodos)"},
        {"name": "Indicators.ADX", "reason": "ADX para confirmar fuerza de tendencia"},
    ])
    
    # === STOP/LIMIT BLOCKS (niveles de stop/target) ===
    proposals["stopLimitBlocks"].extend([
        {"name": "Stop/Limit Price Levels.BollingerBands", "reason": "Stop en bandas de Bollinger"},
        {"name": "Stop/Limit Price Ranges.ATR", "reason": "Rango de stop basado en ATR"},
        {"name": "Stop/Limit Price Levels.SuperTrend", "reason": "Stop en línea SuperTrend"},
        {"name": "Stop/Limit Price Levels.SMA", "reason": "Stop en media móvil simple"},
    ])
    
    return proposals


def _propose_builder_config(analysis: dict) -> dict:
    """Genera propuesta de configuración de builder con bloques organizados por categoría."""
    proposal = {
        "strategy_type": "simple",
        "market_sides": "short",
        "slpt": {},
        "sessions": [],
        "building_blocks": {
            "signals": [],
            "indicators": [],
            "stopLimitBlocks": [],
        },
        "risk": {},
        "rankings": {},
    }
    
    atr = analysis["volatility"].get("atr_14", 0)
    
    if atr > 0:
        proposal["slpt"] = {
            "sl_required": True,
            "pt_required": True,
            "sl_atr_based": True,
            "pt_atr_based": True,
            "sl_atr_multiple": 2.0,
            "pt_atr_multiple": 4.0,
            "note": f"SL = 2x ATR ({atr*2:.2f}), PT = 4x ATR ({atr*4:.2f})",
        }
    else:
        proposal["slpt"] = {
            "sl_required": True,
            "pt_required": True,
            "sl_atr_based": True,
            "pt_atr_based": True,
            "sl_atr_multiple": 2.0,
            "pt_atr_multiple": 4.0,
        }
    
    # === Ventana horaria: por VOLATILIDAD, no por dirección ===
    # El sesgo direccional por hora no es significativo (ver _find_best_hours),
    # así que aislar "las mejores horas para shorts" es ruido. Lo correcto es
    # excluir las horas muertas y dejar que las señales hagan el trabajo direccional.
    hourly = analysis.get("sessions", {}).get("hourly_analysis", {}) or {}
    hours_data = hourly.get("hours", [])

    if hours_data:
        # Horas cuya volatilidad está por encima del promedio del día
        avg_range = sum(h["avg_range_pct"] for h in hours_data) / len(hours_data)
        liquid = [h["hour"] for h in hours_data if h["avg_range_pct"] >= avg_range]
        dead = sorted(set(h["hour"] for h in hours_data) - set(liquid))

        proposal["sessions"] = sorted(liquid)
        proposal["dead_hours"] = dead
        proposal["session_note"] = (
            f"Operar en las horas líquidas (rango >= promedio {avg_range:.3f}%): "
            f"{sorted(liquid)}. Excluir horas muertas: {dead}."
        )
        if hourly.get("directional_edge"):
            proposal["session_note"] += (
                " Sesgo direccional significativo en: "
                f"{[h['hour'] for h in hourly['directional_edge']]}."
            )
        else:
            proposal["session_note"] += (
                " Sin sesgo direccional significativo por hora — el filtro horario "
                "NO debe elegirse por dirección."
            )
    else:
        proposal["sessions"] = [8, 9, 13, 14, 15]
        proposal["session_note"] = "Sesión por defecto: apertura Londres y NY"
    
    # === Building blocks organizados por categoría ===
    # NOTA: no se adjuntan parámetros inventados. Los parámetros reales de cada bloque
    # se preservan automáticamente al construir el .sqb desde el catálogo origen con
    # sqb_builder.build_recommended_sqb(), que mantiene la firma exacta de StrategyQuant.
    for cat, inds in analysis.get("indicators", {}).items():
        for ind in inds:
            block = {
                "name": ind["name"],
                "reason": ind["reason"],
            }
            proposal["building_blocks"][cat].append(block)
    
    proposal["risk"] = {
        "fixed_amount": 250,
        "max_lots": 3,
        "drawdown_pct": 20,
        "max_trades_per_day": 5,
        "note": "Risk conservador: $250/trade, max 5 trades/día, 20% drawdown",
    }
    
    proposal["rankings"] = {
        "fitness_criteria": "ReturnDDRatio",
        "max_strategies": 1000,
        "conditions": [
            {"column": "ReturnDDRatio", "comparator": ">=", "value": "1.5"},
            {"column": "NumberOfTrades", "comparator": ">=", "value": "100"},
            {"column": "ProfitFactor", "comparator": ">=", "value": "1.3"},
            {"column": "SharpeRatio", "comparator": ">=", "value": "1.0"},
            {"column": "DrawdownPct", "comparator": "<=", "value": "15"},
        ],
    }
    
    return proposal
