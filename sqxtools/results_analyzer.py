"""Análisis de resultados de un build de SQX: qué sobrevivió y qué mató el embudo.

Entradas:
  - CSV de estrategias exportado por SQX (SaveToFiles → ExportDatabank, formato CSV/semicolon)
    o cualquier CSV con columnas estándar de SQX (Net Profit, Profit Factor, ...).
  - Opcional: el .cfx del builder (para conocer los umbrales de los filtros de rankings).
  - Opcional: CSVs de databanks intermedios (--stages "1. Seq FAILED:archivo.csv,...")
    para reconstruir el embudo: cuántos entran, cuántos muere cada filtro.

Reporte:
  - Distribución de métricas de los survivors (PF, WLR, trades, DD, duración)
  - Margen de cada survivor sobre cada filtro del builder (¿pasó raspando?)
  - Embudo: tamaño de cada etapa y mortalidad por filtro
  - Sugerencias de calibración basadas en los datos
"""
from __future__ import annotations

import csv
import re
import statistics
from pathlib import Path

from .parser import parse_cfx

# Alias de columnas de SQX (normalizadas: minúsculas, sin espacios/puntos)
ALIASES = {
    "netprofit": ["netprofit", "net profit", "net_profit"],
    "profitfactor": ["profitfactor", "profit factor", "pf"],
    "winlossratio": ["winlossratio", "win/loss ratio", "win loss ratio", "wlr"],
    "percentprofitable": ["percentprofitable", "%win", "win%", "percent profitable"],
    "numberoftrades": ["numberoftrades", "#trades", "trades", "number of trades"],
    "maxdrawdownpct": ["maxdrawdownpct", "max drawdown %", "drawdown%", "drawdown pct"],
    "sharperatio": ["sharperatio", "sharpe ratio", "sharpe"],
    "returnddratio": ["ret/dd ratio", "ret/ddratio", "retddratio", "ret/dd"],
    "timeinmarket": ["timeinmarket", "time in market", "avgtimeinmarket"],
    "strategyname": ["strategyname", "strategy name", "name", "strategy"],
}


def _norm_col(c: str) -> str:
    return re.sub(r"[\s._%#/]+", "", c.lower())


def _canonical(col: str) -> str | None:
    n = _norm_col(col)
    for canon, aliases in ALIASES.items():
        if _norm_col(canon) == n or n in {_norm_col(a) for a in aliases}:
            return canon
    return None


def load_strategies_csv(path: str | Path) -> tuple[list[dict], list[str]]:
    """Lee un CSV exportado de SQX (coma o ;). Devuelve (rows, columnas_canónicas_no_encontradas)."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8-sig", errors="replace")
    delim = ";" if raw.count(";") > raw.count(",") else ","
    reader = csv.DictReader(raw.splitlines(), delimiter=delim)
    rows: list[dict] = []
    unmapped: set[str] = set()
    for r in reader:
        row: dict = {}
        for k, v in (r or {}).items():
            if k is None:
                continue
            canon = _canonical(k)
            if canon:
                row[canon] = _num(v)
            else:
                unmapped.add(k)
        if row:
            rows.append(row)
    return rows, sorted(unmapped)


def _num(v):
    """Número si lo es; si no, string limpio (nombres de estrategias, etc.)."""
    if v is None:
        return None
    s = str(v).strip().replace("%", "").replace("$", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", s):
        s = s.replace(",", "")          # 1,500.5 → 1500.5 (separador de miles)
    if s in ("", "-", "N/A"):
        return None
    try:
        return float(s)
    except ValueError:
        return s


def _pct(vals: list[float], p: float) -> float:
    if not vals:
        return 0.0
    vs = sorted(vals)
    idx = min(int(p * len(vs)), len(vs) - 1)
    return vs[idx]


def builder_thresholds(cfx_path: str | Path | None) -> dict[str, tuple[str, float]]:
    """Extrae los filtros activos de rankings del builder (.cfx)."""
    if not cfx_path:
        return {}
    cfg = parse_cfx(cfx_path)
    rk = getattr(cfg, "rankings", None) or {}
    conds: dict[str, tuple[str, float]] = {}
    for f in rk.get("conditions") or []:
        if not f.get("use"):
            continue
        left = (f.get("left_side") or {}).get("column", {}).get("column", "")
        col = _canonical(left)
        comp = f.get("comparator", ">=")
        right = f.get("right_side") or {}
        val = right.get("numeric")
        if col and comp in (">=", "<=", ">", "<") and val is not None:
            try:
                conds[col] = (comp, float(val))
            except (TypeError, ValueError):
                pass
    return conds


def funnel(stages: list[tuple[str, list[dict]]]) -> list[str]:
    """Reconstruye el embudo a partir de etapas sucesivas (cada una = post-filtro)."""
    out = []
    prev_n = None
    for name, rows in stages:
        n = len(rows)
        if prev_n is None:
            out.append(f"  {name}: {n}")
        else:
            killed = prev_n - n
            pct = 100 * killed / prev_n if prev_n else 0
            out.append(f"  {name}: {n}  (⬅ {killed} eliminados, {pct:.0f}% del paso anterior)")
        prev_n = n
    return out


def margin_over_filters(rows: list[dict], thresholds: dict[str, tuple[str, float]]) -> list[str]:
    """¿Cuánto margen tuvo cada survivor sobre cada filtro? (¿pasó raspando?)"""
    out = []
    for col, (cmp_, thr) in thresholds.items():
        vals = [r.get(col) for r in rows if r.get(col) is not None]
        if not vals:
            continue
        if cmp_ in (">=", ">"):
            n_tight = sum(1 for v in vals if v < thr * 1.10)  # <10% sobre el piso
            worst = min(vals)
            out.append(f"  {col} ≥ {thr:g}: margen mínimo {worst:g} · "
                       f"{n_tight}/{len(vals)} pasaron con <10% de margen")
        elif cmp_ in ("<=", "<"):
            n_tight = sum(1 for v in vals if v > thr * 0.90)
            worst = max(vals)
            out.append(f"  {col} ≤ {thr:g}: peor valor {worst:g} · "
                       f"{n_tight}/{len(vals)} pasaron con <10% de margen")
    return out


def distribution(rows: list[dict]) -> list[str]:
    out = []
    for col in ("netprofit", "profitfactor", "winlossratio", "numberoftrades",
                "maxdrawdownpct", "sharperatio", "timeinmarket"):
        vals = [r.get(col) for r in rows if r.get(col) is not None]
        if not vals:
            continue
        med = statistics.median(vals)
        out.append(f"  {col:16s} mediana {med:g} · min {min(vals):g} · max {max(vals):g} · "
                   f"p25 {_pct(vals, 0.25):g} · p75 {_pct(vals, 0.75):g}")
    return out


def analyze_results(csv_path: str | Path, builder_cfx: str | Path | None = None,
                    stages: list[tuple[str, str]] | None = None) -> str:
    rows, unmapped = load_strategies_csv(csv_path)
    has_metrics = any(
        r.get(c) is not None for r in rows
        for c in ("netprofit", "profitfactor", "winlossratio", "numberoftrades"))
    if not rows or not has_metrics:
        return "ERROR: el CSV no contiene estrategias con métricas legibles (¿export correcto?)"
    L: list[str] = []
    L.append(f"# Análisis de resultados: {Path(csv_path).name}")
    L.append(f"Estrategias: {len(rows)}")
    if unmapped:
        L.append(f"Columnas no reconocidas (ignoradas): {', '.join(unmapped)}")
    L.append("")

    L.append("## Distribución de los survivors")
    L.extend(distribution(rows))
    L.append("")

    thr = builder_thresholds(builder_cfx) if builder_cfx else {}
    if thr:
        L.append("## Margen sobre los filtros del builder")
        L.extend(margin_over_filters(rows, thr))
        tight_hint = []
        for col, (cmp_, t) in thr.items():
            vals = [r.get(col) for r in rows if r.get(col) is not None]
            if not vals:
                continue
            if cmp_ == ">=":
                med = statistics.median(vals)
                if med < t * 1.25:
                    tight_hint.append(f"{col} (mediana {med:g} vs filtro {t:g} — el filtro "
                                      f"está cortando en la mediana: los survivors son los del tail)")
        if tight_hint:
            L.append("")
            L.append("⚠️ Filtros que están seleccionando por tail (mediana del survivor cerca del umbral):")
            L.extend(f"  - {h}" for h in tight_hint)
        L.append("")

    if stages:
        parsed = []
        for name, path in stages:
            r2, _ = load_strategies_csv(path)
            parsed.append((name, r2))
        L.append("## Embudo (mortalidad por etapa)")
        L.extend(funnel(parsed))
        L.append("")

    L.append("## Sugerencias")
    pf = [r["profitfactor"] for r in rows if r.get("profitfactor") is not None]
    wlr = [r["winlossratio"] for r in rows if r.get("winlossratio") is not None]
    if pf and statistics.median(pf) > 1.6:
        L.append("  - La mediana de PF de los survivors está bien por encima del filtro: "
                 "el filtro de PF no está siendo el cuello de botella.")
    if wlr and statistics.median(wlr) < 1.55:
        L.append("  - WLR de survivors cerca del filtro: si querés más win rate, el cambio es "
                 "RRR (bajarlo), no el filtro WLR.")
    L.append("  - Para el próximo ciclo: activá el A/B (3 builds inactivos en el project) y "
             "pasá los CSV de cada databank a --stages para ver qué filtro mata más.")
    return "\n".join(L)
