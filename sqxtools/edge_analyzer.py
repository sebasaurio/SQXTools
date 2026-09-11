"""Edge Analyzer — analiza datos históricos para encontrar ventajas del mercado.

Propuesta de building blocks separada en categorías:
- signals: Señales de entrada (RSIFalling, ADXHigher, etc.)
- indicators: Indicadores de confirmación (Indicators.RSI, Indicators.MACD, etc.)
- stopLimitBlocks: Niveles de stop/target (Stop/Limit Price Levels.RSI, etc.)
"""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Any
from datetime import datetime


# Mapeo de señales propuestas a categorías y parámetros típicos en StrategyQuant
SIGNAL_CATALOG = {
    # Señales (entry signals)
    "SuperTrendDownTrend": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "10", "#Multiplier#": "3"}},
    "IsDowntrend": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "20"}},
    "RSIFalling": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "14", "#Level#": "50"}},
    "MACDSignalFalling": {"category": "signals", "params": {"#Chart#": "Main", "#Fast#": "12", "#Slow#": "26", "#Signal#": "9"}},
    "MACDMainFalling": {"category": "signals", "params": {"#Chart#": "Main", "#Fast#": "12", "#Slow#": "26"}},
    "ADXHigher": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "14", "#Level#": "25"}},
    "ATRRising": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "14"}},
    "ATRCrossUp": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "14"}},
    "ATRCrossDown": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "14"}},
    "BollingerBandsOutside": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "20", "#Deviation#": "2"}},
    "ADXRising": {"category": "signals", "params": {"#Chart#": "Main", "#Period#": "14"}},
    
    # Indicadores (confirmation indicators)
    "Indicators.RSI": {"category": "indicators", "params": {"#Chart#": "Main", "#Period#": "14"}},
    "Indicators.MACD": {"category": "indicators", "params": {"#Chart#": "Main", "#Fast#": "12", "#Slow#": "26", "#Signal#": "9"}},
    "Indicators.ATR": {"category": "indicators", "params": {"#Chart#": "Main", "#Period#": "14"}},
    "Indicators.ADX": {"category": "indicators", "params": {"#Chart#": "Main", "#Period#": "14"}},
    "Indicators.SuperTrend": {"category": "indicators", "params": {"#Chart#": "Main", "#Period#": "10", "#Multiplier#": "3"}},
    "Indicators.BollingerBands": {"category": "indicators", "params": {"#Chart#": "Main", "#Period#": "20", "#Deviation#": "2"}},
    "Indicators.EMA": {"category": "indicators", "params": {"#Chart#": "Main", "#Period#": "20"}},
    "Indicators.SMA": {"category": "indicators", "params": {"#Chart#": "Main", "#Period#": "50"}},
    
    # Stop/Limit Price Levels (niveles de stop/target basados en indicadores)
    "Stop/Limit Price Levels.RSI": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Period#": "14", "#Level#": "30"}},
    "Stop/Limit Price Levels.MACD": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Fast#": "12", "#Slow#": "26"}},
    "Stop/Limit Price Levels.ATR": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Period#": "14"}},
    "Stop/Limit Price Levels.SuperTrend": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Period#": "10", "#Multiplier#": "3"}},
    "Stop/Limit Price Levels.BollingerBands": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Period#": "20", "#Deviation#": "2"}},
    "Stop/Limit Price Levels.EMA": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Period#": "20"}},
    "Stop/Limit Price Levels.SMA": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Period#": "50"}},
    "Stop/Limit Price Ranges.ATR": {"category": "stopLimitBlocks", "params": {"#Chart#": "Main", "#Period#": "14"}},
}


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
            "best_trading_hours": _find_best_hours(df),
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


def _find_best_hours(df: pd.DataFrame) -> list[dict]:
    if "hour" not in df.columns:
        return []
    
    hourly = df.groupby("hour").agg({
        "range_pct": "mean",
        "returns": ["mean", "count"],
    })
    hourly.columns = ["avg_range", "avg_return", "count"]
    hourly = hourly[hourly["count"] >= 50]
    hourly["short_score"] = hourly["avg_range"] * (-hourly["avg_return"].clip(upper=0))
    
    best = hourly.nlargest(3, "short_score")
    return [
        {"hour": int(h), "avg_range_pct": round(v["avg_range"], 3), "avg_return_pct": round(v["avg_return"] * 100, 4)}
        for h, v in best.iterrows()
    ]


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
    
    best_hours = analysis.get("sessions", {}).get("best_trading_hours", [])
    if best_hours:
        hours = [h["hour"] for h in best_hours]
        proposal["sessions"] = hours
        proposal["session_note"] = f"Mejores horas para shorts: {hours}"
    else:
        proposal["sessions"] = [8, 9, 13, 14, 15]
        proposal["session_note"] = "Sesión por defecto: apertura Londres y NY"
    
    # === Building blocks con parámetros y valores por defecto ===
    for cat, inds in analysis.get("indicators", {}).items():
        for ind in inds:
            block = {
                "name": ind["name"],
                "reason": ind["reason"],
                "params": {},
            }
            # Buscar parámetros en el catálogo
            if ind["name"] in SIGNAL_CATALOG:
                block["params"] = SIGNAL_CATALOG[ind["name"]].get("params", {})
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
