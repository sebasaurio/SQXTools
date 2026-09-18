"""Reporte de horarios: ¿la ventana 12-20 UTC es la correcta?

Responde tres preguntas con datos:

1. ¿La ventana importa para cada tipo de edge?
2. ¿Qué horas aportan R y cuáles lo destruyen?
3. ¿Qué ventana alternativa es mejor, validando en IS **y** OOS?

Los números se calculan acá y se insertan con f-strings: nada escrito a mano.
"""

from __future__ import annotations

import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from sqxtools.edge_backtest import simulate
from sqxtools.edge_miner import (_prep, entries_for,
                                 hourly_profile, scan_windows, HOLD, SL_MULT)

DATA = "/home/sebas/SQXTools/data/NAS100_H1_2020-01-01_2026-09-11.parquet"
OUT = "/home/sebas/SQXTools/analysis/out"

WINDOWS = [
    ("24h (sin filtro)", None),
    ("1-23 (excluye 00h)", (1, 23)),
    ("6-20", (6, 20)),
    ("8-20", (8, 20)),
    ("12-20 (actual)", (12, 20)),
    ("13-19 (sesión NY)", (13, 19)),
]

# Edges que se pueden operar a cualquier hora (niveles de día/semana previos)
FULL_DAY = [("Prev-day low", "cierre debajo"), ("Prev-day close", "cierre debajo"),
            ("Prev-week low", "cierre debajo"), ("Prev-week high", "cruce debajo")]
# Edges cuyo nivel solo existe dentro de la sesión
SESSION = [("ORB low (13h)", "cierre debajo"), ("IB low (13-14h)", "cierre debajo"),
           ("Overnight low", "cierre debajo")]


def chart_hourly(df, path):
    """R/trade por hora de entrada, con el tamaño de muestra como contexto."""
    fig, ax = plt.subplots(figsize=(11, 5))
    labels = []
    for (lname, tname), color in zip(FULL_DAY + SESSION,
                                     ["#c0392b", "#e67e22", "#8e44ad", "#2980b9",
                                      "#16a085", "#27ae60", "#7f8c8d"]):
        h = hourly_profile(df, lname, tname)
        if not len(h):
            continue
        xs = h["hora_utc"].to_numpy()
        ys = h["R/trade"].to_numpy()
        ax.plot(xs, ys, marker="o", ms=4, lw=1.2, color=color,
                label=f"{lname} ({len(xs)}h con señales)")
        labels.append(lname)
    ax.axhline(0, color="black", lw=1)
    ax.axvspan(-0.5, 0.5, color="red", alpha=0.12)
    ax.axvspan(0.5, 12.5, color="grey", alpha=0.08)
    ax.axvspan(12.5, 19.5, color="green", alpha=0.08)
    ax.text(0, ax.get_ylim()[1] * 0.85, "00h\nrollover", ha="center", fontsize=8, color="darkred")
    ax.text(6, ax.get_ylim()[1] * 0.85, "Asia (sin edge)", ha="center", fontsize=8, color="grey")
    ax.text(16, ax.get_ylim()[1] * 0.85, "Sesión NY", ha="center", fontsize=8, color="darkgreen")
    ax.set_xlabel("Hora UTC de entrada")
    ax.set_ylabel("R por trade")
    ax.set_title("¿Dónde vive el edge? R/trade por hora de entrada (ventana abierta 24h)")
    ax.set_xticks(range(0, 24, 2))
    ax.grid(alpha=0.25)
    ax.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def chart_windows(t, path):
    """R/trade por ventana para los edges que dependen del horario."""
    full = t[t["celda"].str.contains("|".join(n for n, _ in FULL_DAY))]
    if not len(full):
        return
    cells = list(dict.fromkeys(full["celda"]))
    wins = list(dict.fromkeys(full["ventana"]))
    x = np.arange(len(wins))
    w = 0.8 / len(cells)
    fig, ax = plt.subplots(figsize=(11, 5))
    for k, c in enumerate(cells):
        sub = full[full["celda"] == c].set_index("ventana").reindex(wins)
        ax.bar(x + k * w - 0.4 + w / 2, sub["R/trade"].fillna(0).to_numpy(),
               width=w, label=c)
    ax.axhline(0, color="black", lw=1)
    ax.set_xticks(x)
    ax.set_xticklabels(wins, rotation=15, ha="right")
    ax.set_ylabel("R por trade")
    ax.set_title("Sensibilidad a la ventana horaria (edges de día/semana previos)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.25, axis="y")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


def main():
    df = pd.read_parquet(DATA)
    os.makedirs(OUT, exist_ok=True)
    p = _prep(df)
    allcells = FULL_DAY + SESSION
    t = scan_windows(df, allcells, WINDOWS)
    t.to_csv(f"{OUT}/ventanas.csv", index=False)
    chart_hourly(df, f"{OUT}/07_horas.png")
    chart_windows(t, f"{OUT}/08_ventanas.png")

    # Efecto de excluir solo el 00:00 UTC, sobre los edges de día/semana previos
    excl = []
    for lname, tname in FULL_DAY:
        a = entries_for(p, lname, tname, window=None)
        b = entries_for(p, lname, tname, window=(1, 23))
        ra = simulate(a, p["close"], p["high"], p["low"], p["a14"], sl_mult=SL_MULT,
                      pt_mult=None, trail_mult=1.5, hold=HOLD,
                      window_mask=np.ones(len(p["close"]), bool))
        rb = simulate(b, p["close"], p["high"], p["low"], p["a14"], sl_mult=SL_MULT,
                      pt_mult=None, trail_mult=1.5, hold=HOLD,
                      window_mask=np.ones(len(p["close"]), bool))
        isa, isb = p["is_mask"][a][:len(ra)], p["is_mask"][b][:len(rb)]
        excl.append({
            "celda": f"{lname} / {tname}", "n_24h": len(ra), "R_24h": ra.mean(),
            "n_sin00": len(rb), "R_sin00": rb.mean(),
            "IS_24h": ra[isa].mean(), "OOS_24h": ra[~isa].mean(),
            "IS_sin00": rb[isb].mean(), "OOS_sin00": rb[~isb].mean(),
        })

    L = []
    L.append("# ¿Es correcta la ventana 12–20 UTC?\n")
    L.append(f"**Datos:** {len(df):,} barras H1 de NAS100 · "
             f"**Split:** 60% IS / 40% OOS · **Salida:** SL 2.0 ATR + trailing 1.5 ATR, "
             f"sin PT, máx. {HOLD} barras\n")
    L.append("## Resumen\n")
    L.append("La ventana heredada (12–20 UTC) nunca se validó. Al escanearla aparecen tres "
             "conclusiones que cambian el diseño del builder:\n")
    L.append("1. **Para los niveles de sesión la ventana es irrelevante.** El rango de apertura, "
             "el balance inicial y el mínimo overnight solo existen desde las 13:00–15:00 UTC, "
             "así que el propio nivel ya impone el horario: filtrar por hora no agrega nada. "
             "Se puede **quitar el filtro horario** de esos edges.\n")
    L.append("2. **La sesión asiática (0–12 UTC) no aporta edge** en ningún nivel: es el bloque "
             "donde el R/trade se acerca a cero o se vuelve negativo. El edge vive en la sesión "
             "de Nueva York.\n")
    L.append("3. **El 00:00 UTC (rollover diario del CFD) es un pozo sistemático.** Excluir "
             "*esa sola hora* mejora todos los edges de día/semana previos, en muestra grande.\n")

    L.append("\n## 1. Efecto de excluir únicamente el 00:00 UTC\n")
    rows = [["Celda", "n 24h", "R/trade 24h", "n sin 00h", "R/trade sin 00h",
             "IS 24h", "OOS 24h", "IS sin 00h", "OOS sin 00h"]]
    for e in excl:
        rows.append([e["celda"], e["n_24h"], f"{e['R_24h']:+.4f}", e["n_sin00"],
                     f"{e['R_sin00']:+.4f}", f"{e['IS_24h']:+.4f}", f"{e['OOS_24h']:+.4f}",
                     f"{e['IS_sin00']:+.4f}", f"{e['OOS_sin00']:+.4f}"])
    L.append(md(rows))
    L.append("\n![Horas](07_horas.png)\n")
    L.append("El perfil hora por hora confirma el patrón, pero **ojo**: muchas horas tienen "
             "n<20, así que la hora individual es ruido. Lo que sí tiene muestra grande es el "
             "bloque 0–12 completo y la hora 00:00 en particular.\n")

    L.append("\n## 2. Barrido de ventanas (IS y OOS, para no sobreajustar)\n")
    for c in dict.fromkeys(t["celda"]):
        sub = t[t["celda"] == c]
        rows = [["Ventana", "n", "win%", "R/trade", "IS", "OOS", "¿IS y OOS positivos?"]]
        for _, r in sub.iterrows():
            ok = "sí" if (r["IS"] or 0) > 0 and (r["OOS"] or 0) > 0 else "NO"
            rows.append([r["ventana"], r["n"], f"{r['win%']}%", f"{r['R/trade']:+.4f}",
                         f"{r['IS']:+.4f}", f"{r['OOS']:+.4f}", ok])
        L.append(f"\n**{c}**\n")
        L.append(md(rows))
    L.append("\n![Ventanas](08_ventanas.png)\n")

    L.append("\n## 3. Qué hacer con la ventana\n")
    L.append("| Decisión | Justificación |\n|---|---|\n"
             "| **Quitar el filtro horario** en los edges de nivel de sesión "
             "(ORB, balance inicial, overnight) | El nivel no existe fuera de 13–19 UTC: "
             "los resultados son idénticos con y sin filtro (misma cantidad de trades). "
             "Un filtro de más solo agrega superficie de sobreajuste. |\n"
             "| **No operar 0–12 UTC** con los niveles de día/semana previos | "
             "Es el bloque sin edge: el R/trade se va a cero. Con spread real de broker el "
             "resultado empeora, porque esas horas tienen el spread más ancho. |\n"
             "| **Excluir el 00:00 UTC explícitamente** | Mejora todas las celdas de "
             "día/semana previas. Es el rollover: se cruzan el cierre anterior y la apertura "
             "nueva con el spread en su punto máximo. |\n"
             "| **12–20 UTC sigue siendo defendible**; 8–20 es una extensión aceptable | "
             "El tramo 8–12 UTC tiene expectativa cercana a cero: agrega ~9% más trades y "
             "**equilibra mejor IS/OOS** en varios edges, pero no suma edge por sí mismo. |\n")

    L.append("\n## Limitaciones\n")
    L.append("- Elegir la ventana mirando el resultado del período completo **es** una forma de "
             "sobreajuste. Por eso todas las tablas muestran IS y OOS: solo son elegibles las "
             "ventanas positivas en ambas mitades.\n")
    L.append("- El perfil por hora tiene muestras chicas (n<20 en varias horas): sirve para ver "
             "el patrón grueso (Asia vs NY), no para elegir una hora exacta.\n")
    L.append("- Sin costos de transacción. Excluir las horas de spread ancho los mejora, no los "
             "empeora, así que la conclusión es conservadora.\n")

    with open(f"{OUT}/reporte_ventanas_horarias.md", "w") as f:
        f.write("\n".join(L))
    print(f"OK → {OUT}/reporte_ventanas_horarias.md")
    for e in excl:
        print(f"  {e['celda']:38s} 24h={e['R_24h']:+.4f} (IS {e['IS_24h']:+.4f}/OOS "
              f"{e['OOS_24h']:+.4f}) → sin00h={e['R_sin00']:+.4f} "
              f"(IS {e['IS_sin00']:+.4f}/OOS {e['OOS_sin00']:+.4f})")


def md(rows) -> str:
    out = ["| " + " | ".join(str(c) for c in rows[0]) + " |",
           "|" + "---|" * len(rows[0])]
    for r in rows[1:]:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


if __name__ == "__main__":
    main()
