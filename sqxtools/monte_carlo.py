"""Monte Carlo analysis sobre una serie de trades (en R o en dinero).

Toma la serie de resultados de trades individuales de un backtest y, en vez de
reportar un único equity path, genera muchas curvas permutando el orden de los
trades. Con ellas se responde a "¿qué tan frágil es este resultado?": tasa de
ruina (bust rate), tasa de estrategias rentables (profit rate), distribución del
máximo drawdown y bandas de percentiles alrededor de la curva media.

Es el complemento de validación que falta entre:
  - `edge_backtest` (te da un R/trade puntual) y
  - los cross-checks MonteCarlo* del Custom Project (que solo aprueban/descartan).

La entrada es la serie de resultados por trade: ya sea la salida de
`sqxtools.edge_backtest.simulate` (R-múltiplos) o una lista de PnL por trade.
El orden de los trades se permuta conservando su distribución: esto expone
secuencias catastróficas y rachas que un único orden no muestra.
"""
from __future__ import annotations

import numpy as np


def equity_paths(r: np.ndarray, n_runs: int = 1000, seed: int | None = None,
                 start_equity: float = 0.0) -> np.ndarray:
    """Genera n_runs curvas de equity permutando la serie de trades.

    Args:
        r: resultados por trade (R o dinero). NaN/inf se descartan.
        n_runs: cuántas permutaciones generar.
        seed: para reproducibilidad (None = aleatorio).
        start_equity: valor inicial de la curva (normalmente 0 para R).

    Returns:
        ndarray shape (n_runs, len(r)+1): fila = una simulación, columna = el
        equity acumulado tras k trades. La columna 0 es start_equity.
    """
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    if len(r) == 0:
        return np.zeros((n_runs, 1))
    rng = np.random.default_rng(seed)
    # Permutar TODOS los trades por simulación (shuffle sin reemplazo) mantiene
    # la distribución de resultados e ignora el orden temporal original.
    shuffled = rng.choice(r, size=(n_runs, len(r)), replace=True)
    cum = np.cumsum(shuffled, axis=1)
    return np.concatenate([np.full((n_runs, 1), start_equity), cum], axis=1)


def _pct(arr: np.ndarray, p: float) -> float:
    return float(np.nanpercentile(arr, p * 100.0))


def max_drawdown_series(eq: np.ndarray) -> np.ndarray:
    """Máximo drawdown (en las mismas unidades de eq) por simulación."""
    peak = np.maximum.accumulate(eq, axis=1)
    dd = eq - peak
    return dd.min(axis=1)


def analyze(r, n_runs: int = 1000, seed: int | None = None,
            ruin_level: float | None = None,
            profitable_level: float = 0.0,
            percentiles: tuple[float, float] = (0.05, 0.95),
            timestamps=None) -> dict:
    """Resumen Monte Carlo de una serie de trades.

    Args:
        r: resultados por trade (R o dinero).
        n_runs: simulaciones.
        seed: reproducibilidad.
        ruin_level: umbral de ruina (ej. -3.0 R, o -50.0 unidades). Si es None
            se omite la tasa de ruina.
        profitable_level: umbral de "ser rentable" al final (default 0).
        percentiles: bandas de percentiles de la curva.
        timestamps: opcional; si se pasa, se agregan trades/año para dar una
            escala temporal a la curva media.

    Returns:
        dict con n, n_runs, bust_rate, profit_rate, max_dd (percentiles y peor),
        expectativa y bandas de la curva media.
    """
    r = np.asarray(r, dtype=float)
    r = r[np.isfinite(r)]
    base = {
        "n_trades": int(len(r)),
        "n_runs": int(n_runs),
        "r_per_trade": round(float(r.mean()), 4) if len(r) else None,
        "r_total": round(float(r.sum()), 2) if len(r) else 0.0,
    }
    if len(r) == 0:
        base["bust_rate"] = None
        base["profit_rate"] = None
        return base

    paths = equity_paths(r, n_runs=n_runs, seed=seed)
    final = paths[:, -1]
    base["profit_rate"] = round(100.0 * float((final > profitable_level).mean()), 1)
    if ruin_level is not None:
        # Ruina = la curva toca el nivel en ALGÚN momento (no solo al final).
        touched = (paths < ruin_level).any(axis=1)
        base["bust_rate"] = round(100.0 * float(touched.mean()), 1)
        base["ruin_level"] = ruin_level

    dd = max_drawdown_series(paths)
    base["max_dd"] = {
        "p50": round(float(np.median(dd)), 2),
        "p95": round(float(_pct(dd, 0.95)), 2),
        "worst": round(float(dd.min()), 2),
    }

    # Bandas de percentiles de la curva: por columna (nº de trade).
    lo, hi = percentiles
    band_lo = np.nanpercentile(paths, lo * 100.0, axis=0)
    band_hi = np.nanpercentile(paths, hi * 100.0, axis=0)
    mean_curve = paths.mean(axis=0)
    base["band"] = {
        "lo_pct": lo, "hi_pct": hi,
        "final_lo": round(float(band_lo[-1]), 2),
        "final_hi": round(float(band_hi[-1]), 2),
        "final_mean": round(float(mean_curve[-1]), 2),
    }

    if timestamps is not None:
        ts = np.asarray(timestamps)[np.isfinite(r)]
        if len(ts):
            try:
                import pandas as pd
                yrs = pd.to_datetime(pd.Series(ts)).dt.year.to_numpy()
                n_years = max(int(yrs.max() - yrs.min() + 1), 1)
                base["years"] = int(n_years)
                base["trades_per_year"] = round(len(r) / n_years, 1)
            except Exception:
                pass
    return base


def format_report(res: dict) -> str:
    """Render legible del dict de analyze()."""
    L = []
    L.append(f"# Monte Carlo ({res['n_runs']} simulaciones · {res['n_trades']} trades)")
    if res.get("r_per_trade") is not None:
        L.append(f"R/trade esperado: {res['r_per_trade']:+.3f}  (total {res['r_total']:+.2f})")
    if res.get("trades_per_year"):
        L.append(f"~{res['trades_per_year']}/año ({res['years']} años)")
    L.append(f"Rentable al final (P>={res.get('profitable_level', 0):g}): {res.get('profit_rate')}%")
    if res.get("bust_rate") is not None:
        L.append(f"Tasa de ruina (toca {res['ruin_level']:g}): {res['bust_rate']}%")
    dd = res.get("max_dd") or {}
    if dd:
        L.append(f"Max drawdown: mediana {dd.get('p50')} · p95 {dd.get('p95')} · peor {dd.get('worst')}")
    b = res.get("band") or {}
    if b:
        L.append(f"Equity final (banda {b['lo_pct']:.0%}–{b['hi_pct']:.0%}): "
                 f"{b['final_lo']} … {b['final_mean']} … {b['final_hi']}")
    return "\n".join(L)
