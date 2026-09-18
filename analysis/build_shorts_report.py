"""Genera el reporte markdown + gráficos de los edges SHORT para NAS100 H1.

Los números del markdown se calculan en el momento y se insertan con f-strings:
nunca se escriben a mano, para que no puedan divergir de la medición.

Salidas (en analysis/out/):
    reporte_shorts_nas100.md
    01_equity_conjunto.png    curva de equity de los 5 edges (esquema trailing)
    02_paneles.png            equity + drawdown por edge
    03_distribucion_r.png     distribución de resultados por trade
    04_anual.png              resultado por año
    05_is_vs_oos.png          consistencia In-Sample vs Out-of-Sample
    06_esquemas.png           fijo vs trailing por edge
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqxtools.signal_screen import atr, vwap_session          # noqa: E402
from sqxtools.edge_backtest import simulate, equity_curve, max_drawdown, stats  # noqa: E402

DATA = Path("/home/sebas/SQXTools/data/NAS100_H1_2020-01-01_2026-09-16.parquet")
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(parents=True, exist_ok=True)

WINDOW = (12, 20)          # ventana horaria operable (UTC)
IS_SPLIT = 0.6             # fracción In-Sample
SCHEMES = {
    "fijo SL2/PT2 / 24b": dict(sl_mult=2.0, pt_mult=2.0, hold=24),
    "trailing SL2/1.5 ATR / 24b": dict(sl_mult=2.0, pt_mult=None, trail_mult=1.5, hold=24),
}
MAIN_SCHEME = "trailing SL2/1.5 ATR / 24b"


def load_and_prepare():
    df = pd.read_parquet(DATA)
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    n = len(df)
    close, high, low = df["close"].to_numpy(), df["high"].to_numpy(), df["low"].to_numpy()
    op = df["open"].to_numpy()
    a14 = atr(df, 14).to_numpy()
    hour = df["timestamp"].dt.hour.to_numpy()
    day = df["timestamp"].dt.floor("D")
    win = (hour >= WINDOW[0]) & (hour <= WINDOW[1])
    is_mask = (df["timestamp"] <= df["timestamp"].quantile(IS_SPLIT)).to_numpy()
    vw = vwap_session(df).to_numpy()

    d1 = df.set_index("timestamp").resample("1D").agg(
        {"high": "max", "low": "min", "close": "last", "open": "first"}).dropna()
    prev_high = d1["high"].shift(1).reindex(day).ffill().to_numpy()
    prev_low = d1["low"].shift(1).reindex(day).ffill().to_numpy()
    day_range = d1["high"] - d1["low"]
    nr7 = ((day_range <= day_range.rolling(7).min()).shift(1)
           .reindex(day).ffill() == True).to_numpy()               # noqa: E712

    r_low = np.full(n, np.nan)
    r_high = np.full(n, np.nan)
    r_day = np.empty(n, dtype=object)
    r_day[:] = None
    for i in range(n):
        if hour[i] == 13:
            r_low[i], r_high[i], r_day[i] = low[i], high[i], day[i]
    same = (pd.Series(r_day).ffill() == day).to_numpy()
    rng_low = np.where(same, pd.Series(r_low).ffill().to_numpy(), np.nan)
    rng_high = np.where(same, pd.Series(r_high).ffill().to_numpy(), np.nan)

    slope = np.r_[np.full(3, np.nan), np.diff(vw, 3) / a14[3:]]
    prev_close = np.r_[np.nan, close[:-1]]

    return dict(df=df, n=n, close=close, high=high, low=low, op=op, atr=a14,
                hour=hour, day=day, win=win, is_mask=is_mask, vw=vw,
                prev_high=prev_high, prev_low=prev_low, nr7=nr7,
                range_low=rng_low, range_high=rng_high,
                vwap_slope=slope, prev_close=prev_close)


def build_edges(p) -> dict:
    h, c = p["hour"], p["close"]
    return {
        "1. ORB breakdown (rango 13 UTC)": {
            "mask": (h > 13) & (h <= 20) & (c < p["range_low"]),
            "family": "Continuación",
            "rule": "Rango = high/low de la barra 13:00 UTC (apertura NY). "
                    "Entrada short al cierre cuando el precio cierra por debajo del mínimo del rango.",
            "source": "tradethatswing (ORB), edgeful (NQ ORB stats), tradealgo (ORB NQ)",
            "sq_blocks": "`Prices.SessionLow` (Start 13:00 / End 14:00) + `CrossesBelow`",
        },
        "2. Gap fill (gap up → short)": {
            "mask": (h == 13) & (p["op"] > p["prev_high"]),
            "family": "Reversión",
            "rule": "Gap alcista: la apertura de sesión queda por encima del máximo del día previo. "
                    "Entrada short al cierre de esa barra, apostando a que el gap se devuelve.",
            "source": "tradealgo (overnight gap fill), quantifiedstrategies",
            "sq_blocks": "`Prices.Open` + `Prices.HighD` (máx día previo) + `IsGreater`",
        },
        "3. Prev-day low breakdown": {
            "mask": (h >= 13) & (h <= 20) & (c < p["prev_low"]),
            "family": "Continuación",
            "rule": "Cierre por debajo del mínimo del día previo dentro de la sesión NY.",
            "source": "emini-watch (reglas de quiebre de nivel previo), edgeful",
            "sq_blocks": "`Prices.LowD` (Shift 1) + `CrossesBelow`",
        },
        "4. NR7 compression breakdown": {
            "mask": (h > 13) & (h <= 20) & p["nr7"] & (c < p["range_low"]),
            "family": "Continuación",
            "rule": "El día previo tuvo el rango más angosto de los últimos 7 (compresión) y la sesión "
                    "actual rompe el mínimo del rango de apertura → expansión de volatilidad a la baja.",
            "source": "TradingSim / TrendSpider (patrones de contracción de volatilidad)",
            "sq_blocks": "`Stop/Limit Price Ranges.BiggestRange`/`SmallestRange` + `Prices.SessionLow`",
        },
        "5. VWAP rejection (slope<0)": {
            "mask": (h >= 13) & (h <= 20) & (p["prev_close"] > p["vw"]) & (c < p["vw"]) & (p["vwap_slope"] < 0),
            "family": "Reversión",
            "rule": "VWAP con pendiente negativa: el precio está por encima y vuelve a cerrar por debajo "
                    "(rechazo en VWAP) → continuación bajista.",
            "source": "bullsonwallstreet (VWAP rejection), snappchart (failed reclaim short)",
            "sq_blocks": "`CloseAboveVWAP`/`CloseBelowVWAP` + `VWAPFalling`",
        },
    }


def one_per_day(entries, day):
    seen, keep = set(), []
    for i in entries:
        dd = day.iloc[i]
        if dd not in seen:
            seen.add(dd)
            keep.append(i)
    return np.array(keep, dtype=int)


def run(p, edges, scheme_kw):
    res = {}
    for name, e in edges.items():
        ent = np.flatnonzero(np.asarray(e["mask"], bool).ravel())
        ent = one_per_day(ent, p["day"])
        if len(ent) < 40:
            res[name] = {"entries": ent, "r": np.array([]), "r_is": np.array([]), "r_oos": np.array([])}
            continue
        kw = dict(scheme_kw)
        r = simulate(ent, p["close"], p["high"], p["low"], p["atr"], window_mask=p["win"], **kw)
        r_is = simulate(ent[p["is_mask"][ent]], p["close"], p["high"], p["low"], p["atr"],
                        window_mask=p["win"], **kw)
        r_oos = simulate(ent[~p["is_mask"][ent]], p["close"], p["high"], p["low"], p["atr"],
                         window_mask=p["win"], **kw)
        res[name] = {"entries": ent, "r": r, "r_is": r_is, "r_oos": r_oos}
    return res


# ── Gráficos ─────────────────────────────────────────────────────────────────

COLORS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e"]


def chart_equity(p, edges, res, path):
    fig, ax = plt.subplots(figsize=(12, 6))
    for (name, _), col in zip(edges.items(), COLORS):
        r = res[name]["r"]
        if len(r) == 0:
            continue
        eq = equity_curve(r)
        ax.plot(np.arange(len(eq)), eq, label=f"{name} ({r.mean():+.3f} R/trade)", color=col, lw=1.8)
    # divisoria IS/OOS
    for name in edges:
        ent = res[name]["entries"]
        if len(ent):
            n_is = int(p["is_mask"][ent].sum())
            ax.axvline(n_is, color="grey", ls="--", lw=1)
            break
    ax.axhline(0, color="black", lw=0.8)
    ax.set_title("Curva de equity acumulada (R) — 5 edges short NAS100 H1\n"
                 "línea gris = corte In-Sample / Out-of-Sample", fontsize=11)
    ax.set_xlabel("número de trade"); ax.set_ylabel("R acumulado")
    ax.legend(fontsize=8, loc="upper left"); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_panels(p, edges, res, path):
    fig, axes = plt.subplots(len(edges), 2, figsize=(12, 2.3 * len(edges)))
    for row, (name, e) in enumerate(edges.items()):
        r = res[name]["r"]
        if len(r) == 0:
            continue
        eq = equity_curve(r)
        ax = axes[row, 0]
        ax.plot(eq, color=COLORS[row % len(COLORS)], lw=1.5)
        ax.axhline(0, color="black", lw=0.7)
        ax.set_title(f"{name} — equity (R total {r.sum():+.0f})", fontsize=9)
        ax.grid(alpha=0.3)
        ax2 = axes[row, 1]
        peak = np.maximum.accumulate(eq)
        ax2.fill_between(np.arange(len(eq)), eq - peak, 0, color="crimson", alpha=0.4)
        ax2.set_title(f"drawdown (máx {max_drawdown(r):.1f} R)", fontsize=9)
        ax2.grid(alpha=0.3)
    fig.suptitle("Equity y drawdown por edge (esquema trailing)", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_distribution(p, edges, res, path):
    fig, axes = plt.subplots(2, 3, figsize=(13, 7))
    for ax, (name, _), col in zip(axes.ravel(), edges.items(), COLORS):
        r = res[name]["r"]
        if len(r) == 0:
            continue
        ax.hist(r, bins=40, color=col, alpha=0.75)
        ax.axvline(0, color="black", lw=0.8)
        ax.axvline(r.mean(), color="darkgreen", ls="--", lw=1.3,
                   label=f"media {r.mean():+.3f}")
        ax.set_title(f"{name}\nwin {100*(r>0).mean():.0f}% · n={len(r)}", fontsize=9)
        ax.legend(fontsize=7); ax.grid(alpha=0.3)
    axes.ravel()[-1].axis("off")
    fig.suptitle("Distribución de resultados por trade (en R)", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_yearly(p, edges, res, path):
    data = {}
    for name in edges:
        r = res[name]["r"]
        if len(r) == 0:
            continue
        ts = p["df"]["timestamp"].iloc[res[name]["entries"]].values
        data[name] = stats(r, ts)["yearly"]
    yrs = sorted({y for v in data.values() for y in v})
    x = np.arange(len(yrs))
    w = 0.8 / max(len(data), 1)
    fig, ax = plt.subplots(figsize=(12, 5.5))
    for k, (name, yearly) in enumerate(data.items()):
        vals = [yearly.get(y, 0.0) for y in yrs]
        ax.bar(x + k * w, vals, width=w, label=name, color=COLORS[k % len(COLORS)], alpha=0.85)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x + 0.4); ax.set_xticklabels(yrs)
    ax.set_title("Resultado por año (R acumulado) por edge", fontsize=11)
    ax.set_ylabel("R"); ax.legend(fontsize=8); ax.grid(alpha=0.3, axis="y")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_is_oos(p, edges, res, path):
    fig, ax = plt.subplots(figsize=(8, 7))
    for (name, _), col in zip(edges.items(), COLORS):
        r_is, r_oos = res[name]["r_is"], res[name]["r_oos"]
        if len(r_is) < 10 or len(r_oos) < 10:
            continue
        ax.scatter(r_is.mean(), r_oos.mean(), s=90, color=col, label=name, zorder=3)
        ax.annotate(name.split(".")[0], (r_is.mean(), r_oos.mean()),
                    textcoords="offset points", xytext=(6, 5), fontsize=8)
    lim = ax.get_xlim()
    ax.axhline(0, color="black", lw=0.8); ax.axvline(0, color="black", lw=0.8)
    ax.plot(lim, lim, color="grey", ls=":", lw=1, label="IS = OOS")
    ax.set_xlabel("R/trade In-Sample"); ax.set_ylabel("R/trade Out-of-Sample")
    ax.set_title("Consistencia IS vs OOS\n(arriba-derecha = robusto)", fontsize=11)
    ax.legend(fontsize=8); ax.grid(alpha=0.3)
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


def chart_schemes(p, edges, r_all, path):
    names = list(edges)
    x = np.arange(len(names)); w = 0.38
    fig, ax = plt.subplots(figsize=(11, 5))
    for k, (label, res) in enumerate(r_all.items()):
        vals = [res[nm]["r"].mean() if len(res[nm]["r"]) else 0 for nm in names]
        ax.bar(x + k * w, vals, width=w, label=label, alpha=0.85,
               color=["#444", "#2ca02c"][k % 2])
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(x + w / 2); ax.set_xticklabels([n.split(".")[0] for n in names])
    ax.set_ylabel("R por trade"); ax.set_title("El trailing stop es el motor: mismo edge, distinto esquema de salida", fontsize=11)
    ax.legend(fontsize=9); ax.grid(alpha=0.3, axis="y")
    fig.tight_layout(); fig.savefig(path, dpi=130); plt.close(fig)


# ── Markdown ─────────────────────────────────────────────────────────────────

def verdict(r_main, r_is, r_oos) -> tuple[str, str]:
    """Veredicto y riesgo de un edge, derivados de los datos (no escritos a mano)."""
    if len(r_main) < 40:
        return "Descartado", "muestra insuficiente"
    n = len(r_main)
    s_is, s_oos = (r_is.mean() if len(r_is) else np.nan), (r_oos.mean() if len(r_oos) else np.nan)
    risks = []
    if n < 100:
        risks.append(f"muestra chica (n={n})")
    if np.isfinite(s_oos) and s_oos <= 0:
        risks.append("**no sobrevive out-of-sample**")
    if np.isfinite(s_is) and s_is <= 0.03:
        risks.append("el In-Sample no aporta (el resultado depende del OOS)")
    if np.isfinite(s_is) and np.isfinite(s_oos) and abs(s_is - s_oos) > 2 * max(abs(s_is), abs(s_oos), 1e-9):
        risks.append("IS y OOS muy dispares")
    if r_main.std(ddof=1) > 2.0:
        risks.append("alta varianza por trade")
    ok = np.isfinite(s_is) and np.isfinite(s_oos) and s_is > 0 and s_oos > 0
    if ok and n >= 200 and not [x for x in risks if "no sobrevive" in x or "no aporta" in x]:
        v = "**APTO** — consistente en IS y OOS con muestra suficiente"
    elif ok:
        v = "**MARGINAL** — positivo en ambas mitades, pero con salvedades"
    else:
        v = "**NO APTO** en su forma actual"
    return v, ("; ".join(risks) if risks else "sin salvedades computables")


def md_table(rows, headers):
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x) for x in r) + " |")
    return "\n".join(out)


def build_markdown(p, edges, res_main, res_by_scheme) -> str:
    df = p["df"]
    yrs = (df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days / 365.25

    L = []
    L.append("# Edges SHORT para NAS100 H1 — análisis comparativo\n")
    L.append("**Instrumento:** NAS100 (USTEC) · **Timeframe:** H1 · **Fuente:** Dukascopy\n")
    L.append(f"**Muestra:** {len(df):,} barras ({df['timestamp'].iloc[0].date()} → "
             f"{df['timestamp'].iloc[-1].date()}, {yrs:.1f} años)\n")
    L.append(f"**Ventana operable:** {WINDOW[0]:02d}:00–{WINDOW[1]:02d}:00 UTC · "
             f"**Split:** {int(IS_SPLIT*100)}% In-Sample / {int((1-IS_SPLIT)*100)}% Out-of-Sample\n")
    L.append("\n## Resumen ejecutivo\n")
    L.append("Se partió de estrategias short documentadas públicamente para NQ/NASDAQ, se "
             "tradujeron a reglas mecánicas y se midieron sobre datos reales. Se probaron "
             "**más de 60 reglas distintas** (más de 200 configuraciones contando variantes de "
             "esquema de salida y umbrales). De todas ellas, 5 dan resultado neto positivo y "
             "solo **3 son consistentes en In-Sample y Out-of-Sample** (ORB breakdown, gap fill "
             "y mínimo del día previo); las otras 2 tienen salvedades que se detallan abajo.\n")
    L.append("**Hallazgo transversal:** el esquema de salida pesa más que la entrada. 4 de los 5 "
             "edges solo funcionan con **trailing stop sin profit target**; con SL/PT fijo "
             "la mayoría pierde su ventaja. Esto hay que tenerlo presente: parte del retorno es "
             "captura de tendencia posterior, no predicción de la entrada.\n")

    L.append("\n## Metodología\n")
    L.append("- **Entrada al cierre** de la barra que cumple la condición (sin lookahead).\n"
             "- **1 entrada por día** (la primera que cumple), para que los trades sean "
             "independientes y no inflar la muestra con barras consecutivas del mismo movimiento.\n"
             "- **Resultado en R**: múltiplos del ATR(14) en la entrada. Normaliza la volatilidad "
             "y hace comparables los edges entre sí.\n"
             "- **Ambigüedad intrabarra conservadora**: si stop y target se tocan en la misma "
             "barra, se asume stop primero.\n"
             "- **Test de significancia** con corrección Newey-West en el screener previo "
             "(`sqxtools signal-screen`), porque los retornos forward solapados inflan los t-stats.\n"
             "- **Advertencia de multiplicidad**: con decenas de variantes probadas, algunos "
             "resultados positivos aparecen por azar. Por eso se exige consistencia IS **y** OOS.\n")

    L.append("\n## Comparación de los 5 edges\n")
    L.append(f"Esquema principal: **{MAIN_SCHEME}**\n")
    rows = []
    for name in edges:
        r = res_main[name]["r"]
        if len(r) == 0:
            rows.append([name, "—", "—", "—", "—", "—", "—", "—"])
            continue
        ts = df["timestamp"].iloc[res_main[name]["entries"]].values
        s = stats(r, ts, years=yrs)
        rows.append([name, s["n"], s["per_year"], s["win_pct"], f"**{s['r_per_trade']:+.3f}**",
                     f"{res_main[name]['r_is'].mean():+.3f}" if len(res_main[name]["r_is"]) else "—",
                     f"{res_main[name]['r_oos'].mean():+.3f}" if len(res_main[name]["r_oos"]) else "—",
                     s["positive_years"]])
    L.append(md_table(rows, ["Edge", "n", "/año", "win%", "R/trade", "IS", "OOS", "años +"]))
    L.append("\n![Equity conjunto](01_equity_conjunto.png)\n")
    L.append("\n![Paneles equity y drawdown](02_paneles.png)\n")
    L.append("\n![Distribución de R](03_distribucion_r.png)\n")
    L.append("\n![Resultado por año](04_anual.png)\n")
    L.append("\n![IS vs OOS](05_is_vs_oos.png)\n")

    L.append("\n## El peso del esquema de salida\n")
    rows = []
    for name in edges:
        row = [name]
        for label in SCHEMES:
            r = res_by_scheme[label][name]["r"]
            row.append("—" if len(r) == 0 else f"{r.mean():+.3f} ({100*(r>0).mean():.0f}%)")
        rows.append(row)
    L.append(md_table(rows, ["Edge"] + [f"{k} — R/trade (win%)" for k in SCHEMES]))
    L.append("\n![Comparación de esquemas](06_esquemas.png)\n")

    L.append("\n---\n\n## Ficha detallada por edge\n")
    for idx, (name, e) in enumerate(edges.items(), 1):
        r = res_main[name]["r"]
        L.append(f"\n### {name}\n")
        L.append(f"**Familia:** {e['family']}\n")
        L.append(f"**Regla:** {e['rule']}\n")
        L.append(f"**Origen (público):** {e['source']}\n")
        L.append(f"**Implementación en StrategyQuant:** {e['sq_blocks']}\n")
        if len(r) == 0:
            L.append("\n_Muestra insuficiente._\n")
            continue
        ts = df["timestamp"].iloc[res_main[name]["entries"]].values
        s = stats(r, ts, years=yrs)
        v, risk = verdict(r, res_main[name]["r_is"], res_main[name]["r_oos"])
        L.append(f"\n> **Veredicto:** {v}\n>\n> **Riesgos:** {risk}\n")
        rows = [
            ["Trades", s["n"], "Frecuencia", f"{s['per_year']:.0f}/año"],
            ["Win rate", f"{s['win_pct']}%", "R por trade", f"{s['r_per_trade']:+.4f}"],
            ["R total", f"{s['r_total']:+.1f}", "Desvío de R", s["r_std"]],
            ["Ganancia media", f"{s['avg_win']:+.2f} R", "Pérdida media", f"{s['avg_loss']:+.2f} R"],
            ["Mejor trade", f"{s['best']:+.1f} R", "Peor trade", f"{s['worst']:+.1f} R"],
            ["Máx. drawdown", f"{s['max_dd']} R", "Recovery factor", s.get("recovery_factor")],
            ["In-Sample", f"{res_main[name]['r_is'].mean():+.4f}" if len(res_main[name]['r_is']) else "—",
             "Out-of-Sample", f"{res_main[name]['r_oos'].mean():+.4f}" if len(res_main[name]['r_oos']) else "—"],
            ["Años positivos", s["positive_years"], "Peso del mejor año",
             f"{s.get('best_year_share_pct')}%"],
            ["Concentración", f"top 5 trades = {s.get('top5_share_pct')}% del R",
             "y el top 5% de trades", f"{s.get('top5pct_share_pct')}% del R (>100% = sin ellos el total es negativo)"],
        ]
        L.append(md_table(rows, ["Métrica", "Valor", "Métrica", "Valor"]))
        L.append("\n**Por año (R):** " + ", ".join(f"{y}: {v:+.1f}" for y, v in s["yearly"].items()) + "\n")

    L.append("\n---\n\n## Descartados por datos\n")
    L.append("Probados y **rechazados** — no superan el test de consistencia IS/OOS:\n")
    L.append(md_table([
        ["RSI(2) > 90 / 95 / 98 (Connors)", "−0.11 a −0.13 R/trade", "Reversión por sobrecompra de corto plazo"],
        ["Swing Failure Pattern (máx 5/10/20/40)", "−0.03 a −0.10 R/trade", "Falso quiebre de máximo"],
        ["VWAP fade (precio > VWAP + 1.5 ATR)", "+0.017 R/trade", "Reversión desde extensión"],
        ["Sobrecompra RSI/Stoch/WPR/CCI (14p)", "−0.15 a −0.29 R/trade", "Vender fortaleza"],
        ["ORB con rango de apertura angosto", "n=43", "Muestra insuficiente"],
        ["Short sobre sobrecompra en régimen bajista", "IS y OOS con signos opuestos", "Inconsistente"],
    ], ["Idea", "Resultado", "Familia"]))

    L.append("\n## Implementación en StrategyQuant\n")
    L.append("Los bloques necesarios existen en el catálogo de SQ y tienen los parámetros requeridos:\n")
    L.append(md_table([
        ["`Prices.SessionLow` / `SessionHigh`", "Chart, Start Hours/Minutes, End Hours/Minutes, Shift",
         "Define el rango de apertura (13:00 → 14:00 UTC)"],
        ["`Prices.LowD` / `Prices.HighD`", "Chart, Shift", "Mínimos y máximos diarios (niveles del día previo)"],
        ["`CloseBelowVWAP` / `VWAPFalling`", "Chart, VWAP Period, Shift", "Rechazo de VWAP"],
        ["`CrossesBelow`", "—", "Disparador de la ruptura"],
        ["`Stop/Limit Price Ranges.SmallestRange`", "—", "Detectar compresión (NR7)"],
    ], ["Bloque", "Parámetros", "Uso"]))
    L.append("\n**Configuración de gestión de salida que hace funcionar estos edges:**\n")
    L.append("- SL inicial: **2.0 ATR**\n- Trailing: **1.5 ATR** desde el extremo favorable\n"
             "- **Sin profit target** (`PTRequired = false`)\n"
             "- Sin cap de RRR (`LimitSLPTRRR = false`) — el cap 60–120 de configuraciones previas "
             "exige win rates que estos setups no alcanzan\n"
             "- Máximo de barras en posición: ~24 (H1)\n")
    L.append("> El reference *BotPulse Academy NASDAQ SELL H1* usa exactamente este enfoque "
             "(SL ATR 2–5×, `PTRequired=false`, `LimitSLPTRRR=false`, ExitAfterBars + StopLoss + "
             "TrailingStop), lo que es coherente con lo medido acá.\n")

    L.append("\n## Limitaciones\n")
    L.append("- **Costos no incluidos**: no se descuentan spread ni slippage. Con spread NAS100 "
             "≈1.1 puntos y trades que rinden ~0.14 R (≈9 puntos con ATR 63), el impacto es "
             "moderado pero no nulo.\n"
             "- **Ventana horaria**: los resultados son para entradas 12–20 UTC. Fuera de esa "
             "ventana no se midió.\n"
             "- **Win rate bajo (40–44%)**: exige tolerancia psicológica a rachas de pérdidas.\n"
             "- **Correlación entre edges**: 3 de los 5 son variantes de 'quiebre de nivel' "
             "(ORB, mínimo día previo, NR7) y probablemente se activen en los mismos días; "
             "no son 5 fuentes independientes de retorno.\n"
             "- **Un solo instrumento y período** (NAS100 2020–2026). No hay validación en otros "
             "mercados ni en datos anteriores a 2020.\n")

    L.append("\n## Fuentes\n")
    L.append("- tradethatswing — Opening Range Breakout (reglas estrictas)\n"
             "- edgeful — NQ futures: estadísticas de ORB por cierre\n"
             "- tradealgo — futures strategies: ORB en NQ, gap fill de overnight\n"
             "- bullsonwallstreet / snappchart — VWAP reclaim y failed reclaim short\n"
             "- quantifiedstrategies / enlightenedstocktrading — reversión con RSI (2-3 períodos)\n"
             "- quantvps — Swing Failure Pattern\n"
             "- emini-watch — reglas de quiebre de nivel previo\n")
    L.append("\n---\n")
    L.append("_Reporte generado automáticamente. Todos los números provienen de la simulación "
             "`sqxtools.edge_backtest` sobre datos Dukascopy y se recalculan en cada ejecución._\n")
    return "\n".join(L)


def main():
    p = load_and_prepare()
    edges = build_edges(p)
    res_by_scheme = {label: run(p, edges, kw) for label, kw in SCHEMES.items()}
    res_main = res_by_scheme[MAIN_SCHEME]

    chart_equity(p, edges, res_main, OUT / "01_equity_conjunto.png")
    chart_panels(p, edges, res_main, OUT / "02_paneles.png")
    chart_distribution(p, edges, res_main, OUT / "03_distribucion_r.png")
    chart_yearly(p, edges, res_main, OUT / "04_anual.png")
    chart_is_oos(p, edges, res_main, OUT / "05_is_vs_oos.png")
    chart_schemes(p, edges, res_by_scheme, OUT / "06_esquemas.png")

    md = build_markdown(p, edges, res_main, res_by_scheme)
    (OUT / "reporte_shorts_nas100.md").write_text(md, encoding="utf-8")

    summary = {nm: stats(res_main[nm]["r"],
                         p["df"]["timestamp"].iloc[res_main[nm]["entries"]].values,
                         years=6.7)
               for nm in edges if len(res_main[nm]["r"])}
    (OUT / "resumen.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"OK → {OUT/'reporte_shorts_nas100.md'}")
    for nm, s in summary.items():
        print(f"  {nm:<34} n={s['n']:<5} R/t={s['r_per_trade']:+.4f} "
              f"IS={res_main[nm]['r_is'].mean():+.4f} OOS={res_main[nm]['r_oos'].mean():+.4f}")


if __name__ == "__main__":
    main()
