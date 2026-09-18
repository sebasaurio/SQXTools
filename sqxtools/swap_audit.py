"""Auditoría de swaps: costo de financiación como % anualizado y su peso real.

Cruza las specs reales del broker (sqx_specs.csv, generado por mt5-sync) con el
comportamiento de una estrategia para responder una pregunta concreta:
"¿cuánto del profit bruto se come el swap si mantengo posiciones N noches?"

Dos salidas complementarias:

1. **Swap anualizado del notional** (`annualized_swap_pct`): convierte el swap
   en puntos por noche al único yardstick comparable entre brokers y modos
   (POINTS vs INTEREST). Un "-701 pts/noche" y un "-6.15" no son comparables
   entre sí; el % anualizado del notional sí lo es. Es la misma técnica que el
   artículo de MQL5 "Honest Backtesting of Swing Strategies on Index CFDs".

2. **Costo vs gross profit** (`swap_drag`): dado el hold promedio (noches), el
   número de round-trips y el profit bruto (suma de profits de los deals, SIN
   descontar swaps), estima qué fracción del edge se consume por financiación.

El swap en puntos por noche se convierte a dinero en la moneda de la cuenta con
point_value = tick_value * (point / tick_size), y el notional = precio * contrato.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path


def _norm(n: str) -> str:
    prev = None
    while prev != n:
        prev = n
        n = re.sub(r"(_exness|[mc])$", "", n)
    return n


@dataclass
class SwapAudit:
    symbol: str
    swap_per_night: float          # en moneda de la cuenta, por 1.0 lote
    swap_annualized_pct: float     # % del notional por año (base 360)
    notional_per_lot: float
    point_value: float
    mode: str                      # points | interest | unknown
    annual_days: int = 360
    drag: dict | None = None       # swap_drag() si se pidió costo sobre profit

    def render(self) -> str:
        L = [f"# Swap audit: {self.symbol}"]
        L.append(f"Swap por noche (1 lote): {self.swap_per_night:+.2f} {self._ccy_label()}")
        L.append(f"Swap anualizado: {self.swap_annualized_pct:+.2f}% del notional "
                 f"(base {self.annual_days}/360)")
        L.append(f"Notional por lote: {self.notional_per_lot:,.2f} · point value: {self.point_value:.5f}")
        L.append(f"Modo: {self.mode}")
        if self.drag:
            L.append(self._render_drag())
        return "\n".join(L)

    def _render_drag(self) -> str:
        d = self.drag or {}
        return (f"Swap total: {d.get('total_swap', 0.0):+.2f} · "
                f"{d.get('swap_share_pct', 0.0):.1f}% del gross profit {d.get('gross_profit', 0.0):+,.0f}")

    def _ccy_label(self) -> str:
        return "unidades de cuenta"


def load_specs(csv_path: str | Path) -> dict[str, dict]:
    """{norm: spec} desde sqx_specs.csv (mt5-sync), con float convertidos."""
    out: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("digits", "") == "" or "NO_EXISTE" in str(r):
                continue
            spec = {k: v for k, v in r.items()}
            for k in ("point", "digits", "spread", "tick_value", "tick_size",
                      "contract", "swap_long", "swap_short"):
                try:
                    spec[k] = float(spec.get(k, "") or 0.0)
                except (TypeError, ValueError):
                    spec[k] = 0.0
            out[_norm(r["name"])] = spec
    return out


def point_value_per_lot(spec: dict) -> float:
    """Valor de un punto del símbolo para 1.0 lote, en moneda de la cuenta."""
    tick_size = spec.get("tick_size", 0.0)
    tick_value = spec.get("tick_value", 0.0)
    point = spec.get("point", 0.0)
    if tick_size <= 0 or not tick_value:
        return 0.0
    return tick_value * (point / tick_size)


def daily_swap_account_ccy(spec: dict, lots: float = 1.0, direction: str = "short",
                           price: float | None = None) -> float:
    """Swap por noche en moneda de la cuenta (modo POINTS asumido).

    El CSV de mt5-sync guarda swap_long/swap_short en puntos (el modo POINTS es
    el estándar en Exness y la mayoría de brokers de CFDs de índice). Para el
    modo INTEREST se necesitaría SYMBOL_SWAP_MODE y no está en el CSV; se marca
    en el reporte como "unknown" salvo override.
    """
    swap = spec.get("swap_long" if direction == "long" else "swap_short", 0.0)
    pv = point_value_per_lot(spec)
    return swap * pv * lots


def notional_account_ccy(spec: dict, lots: float = 1.0, price: float | None = None) -> float:
    contract = spec.get("contract", 0.0)
    if price is None:
        price = spec.get("price", 0.0) or 0.0
    return price * contract * lots


def annualized_swap_pct(spec: dict, lots: float = 1.0, direction: str = "short",
                        price: float | None = None, annual_days: int = 360) -> tuple[float, float, float, float]:
    """(swap_por_noche, notional, pct_noche, pct_anio).

    pct_anio es el % anualizado del notional — el yardstick comparable entre
    brokers y modos. En modo INTEREST coincide exactamente con SYMBOL_SWAP_*;
    en modo POINTS es la conversión a "lo que económicamente es".
    """
    swap = daily_swap_account_ccy(spec, lots=lots, direction=direction, price=price)
    notional = notional_account_ccy(spec, lots=lots, price=price)
    pct_night = (swap / notional * 100.0) if notional > 0 else 0.0
    return swap, notional, pct_night, pct_night * annual_days


def swap_drag(swap_per_night: float, avg_hold_nights: float, n_trades: int,
              gross_profit: float) -> dict:
    """Costo total del swap y su fracción del profit bruto.

    Args:
        swap_per_night: swap por noche por trade (moneda de la cuenta).
        avg_hold_nights: noches promedio en posición por round-trip.
        n_trades: número de round-trips.
        gross_profit: profit bruto (suma de profits de deals, SIN swap).

    Returns:
        total_swap, swap_share_pct (fracción del gross profit consumida).
    """
    total = swap_per_night * avg_hold_nights * n_trades
    # Fracción consumida en MAGNITUD positiva; la dirección (costo/ingreso) ya
    # la comunica el signo de total_swap. Un swap negativo que come el 28% del
    # profit bruto se reporta como 28.0, no -28.0.
    share = abs(100.0 * total / gross_profit) if gross_profit else 0.0
    return {
        "total_swap": round(total, 2),
        "gross_profit": round(gross_profit, 2),
        "swap_share_pct": round(share, 1),
    }


def audit(csv_path: str | Path, symbol: str, direction: str = "short",
          lots: float = 1.0, price: float | None = None,
          avg_hold_nights: float | None = None, n_trades: int | None = None,
          gross_profit: float | None = None) -> SwapAudit:
    """Audita el swap de un símbolo y opcionalmente su costo sobre el profit.

    Si se pasan avg_hold_nights+n_trades+gross_profit, el resultado adjunta el
    swap_drag en el atributo `drag`.
    """
    specs = load_specs(csv_path)
    key = _norm(symbol)
    spec = specs.get(key)
    if not spec:
        raise ValueError(f"Símbolo '{symbol}' no está en {csv_path} "
                         f"(normalizado '{key}'). Disponibles: {sorted(set(specs))[:10]}...")

    pv = point_value_per_lot(spec)
    swap, notional, _, pct_year = annualized_swap_pct(
        spec, lots=lots, direction=direction, price=price)

    mode = "points"  # CSV de mt5-sync = modo POINTS (estándar CFDs índice)
    if not pv:
        mode = "unknown"

    a = SwapAudit(symbol=symbol, swap_per_night=swap, swap_annualized_pct=pct_year,
                  notional_per_lot=notional, point_value=pv, mode=mode)
    if avg_hold_nights is not None and n_trades is not None and gross_profit is not None:
        a.drag = swap_drag(swap, avg_hold_nights, n_trades, gross_profit)
    return a
