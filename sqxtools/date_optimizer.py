"""Date Range Optimizer — encuentra rangos IS/OOS óptimos basados en datos históricos.

Analiza el mercado para detectar:
- Regímenes de volatilidad (alto, medio, bajo)
- Cambios estructurales (tendencias, correlaciones)
- Períodos representativos para IS y OOS
- Walk-forward óptimo
"""

import pandas as pd
import numpy as np
from typing import Any
from datetime import timedelta


def optimize_date_ranges(
    df: pd.DataFrame,
    is_ratio: float = 0.6,  # 60% IS, 40% OOS
    min_is_years: float = 3.0,
    min_oos_years: float = 1.5,
    num_oos_periods: int = 3,
) -> dict[str, Any]:
    """Analiza datos históricos y propone rangos IS/OOS óptimos.
    
    Args:
        df: DataFrame con timestamp, open, high, low, close, volume
        is_ratio: Porcentaje de datos para IS (0-1)
        min_is_years: Mínimo años para IS
        min_oos_years: Mínimo años para OOS
        num_oos_periods: Cantidad de períodos OOS para walk-forward
        
    Returns:
        Análisis completo con propuestas de fechas
    """
    analysis = {
        "data_info": {},
        "regimes": [],
        "structural_breaks": [],
        "proposals": [],
        "recommendation": {},
    }
    
    # === Info básica ===
    df = df.copy()
    df = df.sort_values("timestamp").reset_index(drop=True)
    df["returns"] = df["close"].pct_change()
    
    total_days = (df["timestamp"].max() - df["timestamp"].min()).days
    total_years = total_days / 365.25
    
    analysis["data_info"] = {
        "date_from": str(df["timestamp"].iloc[0]),
        "date_to": str(df["timestamp"].iloc[-1]),
        "total_bars": len(df),
        "total_days": total_days,
        "total_years": round(total_years, 2),
    }
    
    # === Detectar regímenes de volatilidad ===
    analysis["regimes"] = _detect_regimes(df)
    
    # === Detectar cambios estructurales ===
    analysis["structural_breaks"] = _detect_structural_breaks(df)
    
    # === Generar propuestas ===
    analysis["proposals"] = _generate_proposals(
        df, analysis, is_ratio, min_is_years, min_oos_years, num_oos_periods
    )
    
    # === Recomendación final ===
    analysis["recommendation"] = _generate_recommendation(analysis)
    
    return analysis


def _detect_regimes(df: pd.DataFrame, window: int = 50) -> list[dict]:
    """Detecta regímenes de volatilidad usando rolling std."""
    df = df.copy()
    df["volatility"] = df["returns"].rolling(window).std() * np.sqrt(252)
    
    # Usar percentiles móviles para clasificar
    vol_series = df["volatility"].dropna()
    
    if len(vol_series) < window * 2:
        return []
    
    # Umbrales fijos basados en percentiles globales
    high_threshold = vol_series.quantile(0.75)
    low_threshold = vol_series.quantile(0.25)
    
    df["regime"] = "normal"
    df.loc[df["volatility"] > high_threshold, "regime"] = "high_vol"
    df.loc[df["volatility"] < low_threshold, "regime"] = "low_vol"
    
    # Encontrar períodos continuos del mismo régimen
    df["regime_change"] = df["regime"] != df["regime"].shift(1)
    df["regime_group"] = df["regime_change"].cumsum()
    
    regimes = []
    for _, group in df.groupby("regime_group"):
        regime_type = group["regime"].iloc[0]
        if regime_type == "normal":
            continue
        
        start = group["timestamp"].iloc[0]
        end = group["timestamp"].iloc[-1]
        duration_days = (end - start).days
        avg_vol = group["volatility"].mean()
        
        if duration_days >= 14:  # Solo regímenes de al menos 14 días
            regimes.append({
                "type": regime_type,
                "start": str(start.date()) if hasattr(start, 'date') else str(start),
                "end": str(end.date()) if hasattr(end, 'date') else str(end),
                "duration_days": duration_days,
                "avg_annual_vol": round(avg_vol * 100, 2),
            })
    
    # Ordenar por duración (los más largos primero)
    regimes.sort(key=lambda x: x["duration_days"], reverse=True)
    return regimes


def _detect_structural_breaks(df: pd.DataFrame, window: int = 100) -> list[dict]:
    """Detecta cambios estructurales usando CUSUM (cumulative sum)."""
    df = df.copy()
    df["returns"] = df["returns"].fillna(0)
    
    # CUSUM de retornos acumulados
    df["cumsum"] = df["returns"].cumsum()
    
    # Detectar puntos donde la tendencia cambia significativamente
    # Usamos el cambio en la pendiente de la curva de retornos acumulados
    df["slope"] = df["cumsum"].rolling(window).apply(
        lambda x: np.polyfit(range(len(x)), x, 1)[0], raw=True
    )
    df["slope_change"] = df["slope"].diff()
    
    # Puntos de cambio significativo (percentil 95)
    threshold = df["slope_change"].abs().quantile(0.95)
    breaks = df[df["slope_change"].abs() > threshold].copy()
    
    structural_breaks = []
    for _, row in breaks.iterrows():
        structural_breaks.append({
            "date": str(row["timestamp"].date()) if hasattr(row["timestamp"], 'date') else str(row["timestamp"]),
            "type": "trend_change",
            "magnitude": round(abs(row["slope_change"]) * 10000, 2),
        })
    
    # Mantener solo los más significativos (máximo 10)
    structural_breaks.sort(key=lambda x: x["magnitude"], reverse=True)
    return structural_breaks[:10]


def _generate_proposals(
    df: pd.DataFrame,
    analysis: dict,
    is_ratio: float,
    min_is_years: float,
    min_oos_years: float,
    num_oos_periods: int,
) -> list[dict]:
    """Genera propuestas de rangos IS/OOS basadas en el análisis."""
    proposals = []
    
    total_days = analysis["data_info"]["total_days"]
    date_from = df["timestamp"].min()
    date_to = df["timestamp"].max()
    
    # === Propuesta 1: Split simple ===
    is_days = int(total_days * is_ratio)
    split_date = date_from + timedelta(days=is_days)
    
    proposals.append({
        "name": "Split Simple",
        "description": f"{is_ratio*100:.0f}% IS / {(1-is_ratio)*100:.0f}% OOS",
        "in_sample": {
            "from": str(date_from.date()) if hasattr(date_from, 'date') else str(date_from),
            "to": str(split_date.date()) if hasattr(split_date, 'date') else str(split_date),
        },
        "out_of_sample": {
            "from": str(split_date.date()) if hasattr(split_date, 'date') else str(split_date),
            "to": str(date_to.date()) if hasattr(date_to, 'date') else str(date_to),
        },
    })
    
    # === Propuesta 2: Walk-forward basado en regímenes ===
    regimes = analysis.get("regimes", [])
    if regimes:
        # Seleccionar regímenes representativos para OOS
        high_vol_regimes = [r for r in regimes if r["type"] == "high_vol"]
        low_vol_regimes = [r for r in regimes if r["type"] == "low_vol"]
        
        if high_vol_regimes:
            # OOS en período de alta volatilidad
            selected = high_vol_regimes[0]
            proposals.append({
                "name": "OOS en Alta Volatilidad",
                "description": f"Test en régimen de alta vol ({selected['avg_annual_vol']}% anual)",
                "in_sample": {
                    "from": str(date_from.date()) if hasattr(date_from, 'date') else str(date_from),
                    "to": selected["start"],
                },
                "out_of_sample": {
                    "from": selected["start"],
                    "to": selected["end"],
                },
            })
        
        if low_vol_regimes:
            # OOS en período de baja volatilidad
            selected = low_vol_regimes[0]
            proposals.append({
                "name": "OOS en Baja Volatilidad",
                "description": f"Test en régimen de baja vol ({selected['avg_annual_vol']}% anual)",
                "in_sample": {
                    "from": str(date_from.date()) if hasattr(date_from, 'date') else str(date_from),
                    "to": selected["start"],
                },
                "out_of_sample": {
                    "from": selected["start"],
                    "to": selected["end"],
                },
            })
    
    # === Propuesta 3: Walk-forward con múltiples períodos ===
    if num_oos_periods > 1 and total_days / 365.25 >= (min_is_years + min_oos_years * num_oos_periods):
        # Dividir en períodos de igual tamaño
        period_days = total_days // (num_oos_periods + 1)
        
        is_end = date_from + timedelta(days=period_days)
        oos_ranges = []
        
        for i in range(num_oos_periods):
            oos_start = is_end + timedelta(days=i * period_days)
            oos_end = oos_start + timedelta(days=period_days)
            if oos_end > date_to:
                oos_end = date_to
            oos_ranges.append({
                "from": str(oos_start.date()) if hasattr(oos_start, 'date') else str(oos_start),
                "to": str(oos_end.date()) if hasattr(oos_end, 'date') else str(oos_end),
            })
        
        proposals.append({
            "name": f"Walk-Forward {num_oos_periods} períodos",
            "description": f"IS + {num_oos_periods} OOS de ~{period_days // 365} años cada uno",
            "in_sample": {
                "from": str(date_from.date()) if hasattr(date_from, 'date') else str(date_from),
                "to": str(is_end.date()) if hasattr(is_end, 'date') else str(is_end),
            },
            "out_of_sample_ranges": oos_ranges,
        })
    
    # === Propuesta 4: IS con regímenes completos ===
    # IS debe incluir al menos un ciclo completo de mercado (alcista + bajista)
    if len(regimes) >= 2:
        # Encontrar el período más largo que incluya al menos 2 regímenes
        all_regime_changes = sorted(set([r["start"] for r in regimes] + [r["end"] for r in regimes]))
        
        if len(all_regime_changes) >= 2:
            # IS desde el primer cambio de régimen hasta el último
            proposals.append({
                "name": "IS con Ciclo Completo",
                "description": "Incluye al menos un ciclo alcista + bajista",
                "in_sample": {
                    "from": all_regime_changes[0],
                    "to": all_regime_changes[-1],
                },
                "out_of_sample": {
                    "from": all_regime_changes[-1],
                    "to": str(date_to.date()) if hasattr(date_to, 'date') else str(date_to),
                },
            })
    
    return proposals


def _generate_recommendation(analysis: dict) -> dict:
    """Genera recomendación final basada en el análisis."""
    total_years = analysis["data_info"]["total_years"]
    regimes = analysis.get("regimes", [])
    
    recommendation = {
        "optimal_is_years": 0,
        "optimal_oos_years": 0,
        "strategy": "",
        "rationale": "",
    }
    
    if total_years < 3:
        recommendation["strategy"] = "insufficient_data"
        recommendation["rationale"] = f"Solo {total_years:.1f} años de datos. Mínimo recomendado: 3 años."
        return recommendation
    
    if total_years < 5:
        # Datos limitados: 70/30
        recommendation["optimal_is_years"] = round(total_years * 0.7, 1)
        recommendation["optimal_oos_years"] = round(total_years * 0.3, 1)
        recommendation["strategy"] = "conservative"
        recommendation["rationale"] = f"Datos limitados ({total_years:.1f} años). Split 70/30 para maximizar datos de entrenamiento."
    
    elif total_years < 8:
        # Datos moderados: 60/40 con walk-forward
        recommendation["optimal_is_years"] = round(total_years * 0.6, 1)
        recommendation["optimal_oos_years"] = round(total_years * 0.4, 1)
        recommendation["strategy"] = "walk_forward"
        recommendation["rationale"] = f"Datos moderados ({total_years:.1f} años). 60/40 con walk-forward de 2-3 períodos."
    
    else:
        # Datos abundantes: 50/50 con walk-forward múltiple
        recommendation["optimal_is_years"] = round(total_years * 0.5, 1)
        recommendation["optimal_oos_years"] = round(total_years * 0.5, 1)
        recommendation["strategy"] = "robust_walk_forward"
        recommendation["rationale"] = f"Datos abundantes ({total_years:.1f} años). 50/50 con walk-forward de 4+ períodos."
    
    # Ajustar por regímenes
    high_vol_count = len([r for r in regimes if r["type"] == "high_vol"])
    if high_vol_count >= 3:
        recommendation["rationale"] += f" Se detectaron {high_vol_count} períodos de alta volatilidad — buena diversidad para OOS."
    
    return recommendation
