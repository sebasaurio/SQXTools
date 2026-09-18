"""Motor de backtest de edges direccionales (short y long) con SL/PT/trailing.

Unifica la simulación que se venía reescribiendo en cada análisis, con las
decisiones de diseño explícitas para que los resultados sean reproducibles:

- **Sin lookahead**: la condición se evalúa con datos hasta el cierre de la barra `t`
  y la entrada es al cierre de `t`.
- **Ambigüedad intrabarra conservadora**: si en una misma barra se tocan stop y
  target, se asume que salta el **stop** primero. Evita sobreestimar resultados.
- **Unidades**: el resultado de cada trade se expresa en múltiplos del ATR en la
  entrada (`R`), lo que normaliza la volatilidad entre regímenes y permite comparar
  edges entre sí independientemente del tamaño de posición.
- **Trailing**: stop inicial a `sl_mult` ATR, que se desplaza a `trail_mult` ATR del
  extremo favorable. Sin `pt_mult`, el trade solo cierra por stop, por trailing o
  por vencimiento de `hold` barras.
- **Concurrencia**: se aplica una regla de "una entrada a la vez" por defecto
  (`one_at_a_time`) para que los R no estén artificialmente correlacionados.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def simulate(entries, close, high, low, atr, *, long: bool = False,
             sl_mult: float = 2.0, pt_mult: float | None = None,
             trail_mult: float | None = None, hold: int = 24,
             window_mask=None, one_at_a_time: bool = False,
             atr_floor: float = 1e-9) -> np.ndarray:
    """Simula una lista de entradas y devuelve el resultado de cada trade en R.

    Args:
        entries: índices (enteros) de las barras de entrada.
        close, high, low, atr: arrays del mismo largo que el histórico.
        long: True para largo, False para short.
        sl_mult: distancia del stop inicial en ATR.
        pt_mult: distancia del target en ATR. None = sin target fijo.
        trail_mult: si se indica, activa el trailing stop a esa distancia en ATR
            del extremo favorable alcanzado. None = sin trailing.
        hold: máximo de barras en posición.
        window_mask: máscara booleana de barras operables (p. ej. la ventana horaria).
        one_at_a_time: si True, ignora entradas que caigan dentro de un trade abierto.
    """
    close = np.asarray(close, dtype=float)
    high = np.asarray(high, dtype=float)
    low = np.asarray(low, dtype=float)
    atr = np.asarray(atr, dtype=float)
    n = len(close)
    sign = 1.0 if long else -1.0
    out: list[float] = []
    bar = -1  # última barra ocupada por un trade

    for i in np.asarray(entries, dtype=int).ravel():
        i = int(i)
        if i < 0 or i >= n:
            continue
        if window_mask is not None and not window_mask[i]:
            continue
        if one_at_a_time and i <= bar:
            continue
        a = atr[i]
        if not np.isfinite(a) or a <= atr_floor:
            continue

        entry = close[i]
        stop = entry - sign * sl_mult * a          # long: stop abajo · short: arriba
        target = None if pt_mult is None else entry + sign * pt_mult * a
        extreme = entry                            # mejor precio alcanzado a favor
        end = min(i + hold, n - 1)
        r = None
        for j in range(i + 1, end + 1):
            hit_stop = (low[j] <= stop) if long else (high[j] >= stop)
            hit_tgt = target is not None and ((high[j] >= target) if long else (low[j] <= target))
            if hit_stop:                            # conservador: stop primero
                # P&L real contra el NIVEL del stop, no contra el riesgo inicial:
                # con trailing el stop ya se movió y puede cerrar en ganancia.
                r = sign * (stop - entry) / a
                break
            if hit_tgt:
                r = sign * (target - entry) / a
                break
            if trail_mult is not None:
                if long:
                    extreme = max(extreme, high[j])
                    stop = max(stop, extreme - trail_mult * a)
                else:
                    extreme = min(extreme, low[j])
                    stop = min(stop, extreme + trail_mult * a)
        if r is None:                               # vencimiento: marca a mercado
            r = sign * (close[end] - entry) / a
        out.append(float(r))
        bar = end

    return np.array(out, dtype=float)


def equity_curve(r: np.ndarray) -> np.ndarray:
    """Curva de equity acumulada en R (empieza en 0)."""
    return np.concatenate([[0.0], np.cumsum(np.asarray(r, dtype=float))])


def wilson_interval(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Intervalo de Wilson para una proporción (win rate) con muestra pequeña.

    A diferencia del intervalo normal p±z·sqrt(p(1-p)/n), Wilson no se degrada
    con n chica ni produce límites fuera de [0,1]. Devuelve (lower, upper).
    65% de 8 trades y 65% de 400 trades NO son igual de confiables; este
    intervalo hace explícita esa diferencia de evidencia.
    """
    if n <= 0:
        return (0.0, 0.0)
    p = wins / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = p + z2 / (2.0 * n)
    half = z * ((p * (1.0 - p) / n) + z2 / (4.0 * n * n)) ** 0.5
    lower = (centre - half) / denom
    upper = (centre + half) / denom
    return max(0.0, lower), min(1.0, upper)


def max_drawdown(r: np.ndarray) -> float:
    """Máxima caída desde un máximo previo de la curva, en R."""
    eq = equity_curve(r)
    peak = np.maximum.accumulate(eq)
    return float((eq - peak).min())


def stats(r: np.ndarray, timestamps=None, years: float | None = None) -> dict:
    """Estadísticas de una serie de trades en R."""
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return {"n": 0}
    wins, losses = r[r > 0], r[r <= 0]
    d: dict = {
        "n": int(len(r)),
        "win_pct": round(100 * float((r > 0).mean()), 1),
        # Intervalo de Wilson sobre el win rate: cuánta evidencia hay detrás.
        "win_pct_lo": round(100 * wilson_interval(len(wins), len(r))[0], 1),
        "win_pct_hi": round(100 * wilson_interval(len(wins), len(r))[1], 1),
        # Expectativa en R-múltiples: cuánto se espera ganar por cada R arriesgado.
        "expectancy_r": round(float(r.mean()), 4),
        "r_per_trade": round(float(r.mean()), 4),
        "r_total": round(float(r.sum()), 1),
        "r_std": round(float(r.std(ddof=1)), 2),
        "r_median": round(float(np.median(r)), 3),
        "avg_win": round(float(wins.mean()), 3) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 3) if len(losses) else 0.0,
        "best": round(float(r.max()), 2),
        "worst": round(float(r.min()), 2),
        "max_dd": round(max_drawdown(r), 1),
        "recovery_factor": round(float(r.sum()) / abs(max_drawdown(r)), 2)
        if max_drawdown(r) != 0 else None,
    }
    if years:
        d["per_year"] = round(len(r) / years, 0)
    if timestamps is not None:
        ts = pd.to_datetime(pd.Series(timestamps))
        yrs = ts.dt.year.to_numpy()
        yearly = {int(y): float(r[yrs == y].sum()) for y in np.unique(yrs)}
        pos = sum(1 for v in yearly.values() if v > 0)
        d["positive_years"] = f"{pos}/{len(yearly)}"
        total = sum(yearly.values())
        if total != 0:
            d["best_year_share_pct"] = round(100 * max(yearly.values()) / total)
        d["yearly"] = {k: round(v, 1) for k, v in yearly.items()}
    # Dependencia de la cola: cuánto del R total aportan los mejores trades
    s = np.sort(r)[::-1]
    if r.sum() > 0:
        d["top5_share_pct"] = round(100 * float(s[:5].sum() / r.sum()), 1)
        d["top5pct_share_pct"] = round(
            100 * float(s[: max(1, len(s) // 20)].sum() / r.sum()), 1)
    return d
