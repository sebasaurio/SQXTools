"""Edge Analyzer — analiza datos históricos para encontrar ventajas del mercado."""

import pandas as pd
import numpy as np
from pathlib import Path
from typing import Any
from datetime import datetime


def analyze_market(
    df: pd.DataFrame,
    symbol: str = "USATECHIDX",
    timeframe: str = "H1",
) -> dict[str, Any]:
    """Analiza datos históricos y propone configuración óptima de builder.
    
    Args:
        df: DataFrame con columnas timestamp, open, high, low, close, volume
        symbol: Nombre del símbolo
        timeframe: Temporalidad
        
    Returns:
        Diccionario con análisis completo y propuestas
    """
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
    
    # === Info básica ===
    analysis["data_info"] = {
        "total_bars": len(df),
        "date_from": str(df["timestamp"].iloc[0]) if "timestamp" in df.columns else "N/A",
        "date_to": str(df["timestamp"].iloc[-1]) if "timestamp" in df.columns else "N/A",
        "avg_close": float(df["close"].mean()),
    }
    
    # === Volatilidad ===
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
    
    # === Análisis por hora (sesiones) ===
    if "timestamp" in df.columns:
        df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
        df["dayofweek"] = pd.to_datetime(df["timestamp"]).dt.dayofweek
        
        # Volatilidad por hora
        hourly_vol = df.groupby("hour")["range_pct"].agg(["mean", "std", "count"])
        hourly_vol.columns = ["avg_range", "std_range", "count"]
        
        # Horas más volátiles
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
    
    # === Patrones de velas ===
    df["body"] = abs(df["close"] - df["open"])
    df["upper_wick"] = df["high"] - df[["open", "close"]].max(axis=1)
    df["lower_wick"] = df[["open", "close"]].min(axis=1) - df["low"]
    df["body_pct"] = df["body"] / (df["high"] - df["low"] + 1e-10) * 100
    
    # Doji (cuerpo pequeño)
    doji = df[df["body_pct"] < 20]
    analysis["patterns"]["doji_pct"] = round(len(doji) / len(df) * 100, 2)
    
    # Velas con mecha superior larga (rechazo a subidas - bueno para shorts)
    short_wick = df[df["upper_wick"] > df["body"] * 2]
    analysis["patterns"]["short_rejection_pct"] = round(len(short_wick) / len(df) * 100, 2)
    
    # Velas con mecha inferior larga (rechazo a bajadas - malo para shorts)
    long_lower = df[df["lower_wick"] > df["body"] * 2]
    analysis["patterns"]["long_lower_wick_pct"] = round(len(long_lower) / len(df) * 100, 2)
    
    # === Tendencia ===
    df["sma_20"] = df["close"].rolling(20).mean()
    df["sma_50"] = df["close"].rolling(50).mean()
    
    # Porcentaje de tiempo en tendencia bajista (SMA20 < SMA50)
    if len(df) >= 50:
        downtrend = df[df["sma_20"] < df["sma_50"]]
        analysis["patterns"]["downtrend_pct"] = round(len(downtrend) / len(df) * 100, 2)
    else:
        analysis["patterns"]["downtrend_pct"] = None
    
    # === Indicadores propuestos ===
    analysis["indicators"] = _propose_indicators(df, analysis)
    
    # === Propuesta de builder ===
    analysis["builder_proposal"] = _propose_builder_config(analysis)
    
    return analysis


def _find_best_hours(df: pd.DataFrame) -> list[dict]:
    """Encuentra las mejores horas para operar basado en volatilidad y dirección."""
    if "hour" not in df.columns:
        return []
    
    hourly = df.groupby("hour").agg({
        "range_pct": "mean",
        "returns": ["mean", "count"],
    })
    hourly.columns = ["avg_range", "avg_return", "count"]
    
    # Filtrar horas con suficientes datos
    hourly = hourly[hourly["count"] >= 50]
    
    # Mejor hora para shorts: alta volatilidad + retorno negativo promedio
    hourly["short_score"] = hourly["avg_range"] * (-hourly["avg_return"].clip(upper=0))
    
    best = hourly.nlargest(3, "short_score")
    return [
        {"hour": int(h), "avg_range_pct": round(v["avg_range"], 3), "avg_return_pct": round(v["avg_return"] * 100, 4)}
        for h, v in best.iterrows()
    ]


def _propose_indicators(df: pd.DataFrame, analysis: dict) -> dict:
    """Propone indicadores óptimos basados en el análisis del mercado."""
    proposals = {
        "trend": [],
        "momentum": [],
        "volatility": [],
        "volume": [],
    }
    
    # === Tendencia ===
    # Si hay tendencia bajista clara, proponer indicadores de continuación
    if analysis["patterns"].get("downtrend_pct", 0) > 55:
        proposals["trend"].extend([
            {"name": "SuperTrendDownTrend", "reason": f"Tendencia bajista dominante ({analysis['patterns']['downtrend_pct']}%)"},
            {"name": "IsDowntrend", "reason": "Confirmación de tendencia"},
            {"name": "MACDMainFalling", "reason": "Momentum bajista"},
        ])
    else:
        proposals["trend"].extend([
            {"name": "SuperTrendDownTrend", "reason": "Tendencia general del mercado"},
            {"name": "IsDowntrend", "reason": "Confirmación de tendencia"},
        ])
    
    # === Momentum ===
    proposals["momentum"].extend([
        {"name": "RSIFalling", "reason": "RSI bajando desde zona alta = entrada más segura para shorts"},
        {"name": "MACDSignalFalling", "reason": "Confirmación de momentum bajista"},
    ])
    
    # Si hay muchos doji, añadir confirmación de volatilidad
    if analysis["patterns"].get("doji_pct", 0) > 10:
        proposals["momentum"].append(
            {"name": "ADXHigher", "reason": f"Alta frecuencia de doji ({analysis['patterns']['doji_pct']}%) — ADX confirma fuerza de tendencia"}
        )
    
    # === Volatilidad ===
    proposals["volatility"].extend([
        {"name": "ATRRising", "reason": "Volatilidad creciente = oportunidades de shorts"},
        {"name": "BollingerBandsOutside", "reason": "Precio fuera de banda bajista = continuación"},
    ])
    
    # Si la volatilidad es alta, añadir ATR cross
    if analysis["volatility"].get("avg_range_pct", 0) > 0.5:
        proposals["volatility"].append(
            {"name": "ATRCrossUp", "reason": f"Volatilidad alta ({analysis['volatility']['avg_range_pct']:.2f}%) — ATR Cross confirma activación"}
        )
    
    return proposals


def _propose_builder_config(analysis: dict) -> dict:
    """Genera propuesta de configuración de builder basada en el análisis."""
    proposal = {
        "strategy_type": "simple",
        "market_sides": "short",
        "slpt": {},
        "sessions": [],
        "signals": [],
        "risk": {},
        "rankings": {},
    }
    
    # === SL/PT basado en volatilidad ===
    atr = analysis["volatility"].get("atr_14", 0)
    avg_range = analysis["volatility"].get("avg_range_pct", 0.5)
    
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
    
    # === Sesiones ===
    best_hours = analysis.get("sessions", {}).get("best_trading_hours", [])
    if best_hours:
        hours = [h["hour"] for h in best_hours]
        proposal["sessions"] = hours
        proposal["session_note"] = f"Mejores horas para shorts: {hours}"
    else:
        proposal["sessions"] = [8, 9, 13, 14, 15]  # Apertura Londres + NY
        proposal["session_note"] = "Sesión por defecto: apertura Londres y NY"
    
    # === Señales propuestas ===
    signals = []
    for cat, inds in analysis.get("indicators", {}).items():
        for ind in inds:
            signals.append(ind["name"])
    proposal["signals"] = signals
    
    # === Risk Management ===
    proposal["risk"] = {
        "fixed_amount": 250,
        "max_lots": 3,
        "drawdown_pct": 20,
        "max_trades_per_day": 5,
        "note": "Risk conservador: $250/trade, max 5 trades/día, 20% drawdown",
    }
    
    # === Rankings ===
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
