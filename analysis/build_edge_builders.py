"""Genera 5 builders de StrategyQuant, uno por cada edge del top-5 medido.

Cada perfil AÍSLA un edge: restringe el catálogo de bloques a los que ese edge
necesita (`set_signals` / `set_indicators`), fija los parámetros del nivel con un
set predefinido de SQ (`fixed_params`) y exige una sola condición de entrada. Así
el builder no puede combinar señales ajenas y lo que genera es, en la práctica,
ese edge.

Los números de desempeño de cada edge, medidos sobre NAS100 H1 con un simulador
propio y con control de azar, están en `analysis/out/edge_miner_baseline.csv`.
Ojo con la columna `exceso`: es lo que importa, no el R/trade absoluto.
"""

from __future__ import annotations

import os
import sys
import zipfile

sys.path.insert(0, "/home/sebas/SQXTools")

from sqxtools.cfx_builder import apply_builder_profile  # noqa: E402

TEMPLATE = "/home/sebas/SQXTools/output/v9_estabilidad.cfx"
PROF = "/home/sebas/SQXTools/perfiles"
OUT = "/home/sebas/SQXTools/output/edges"
os.makedirs(OUT, exist_ok=True)

# Ventana 12-20 UTC (43200-72000 segundos desde medianoche). En el análisis de
# horarios, 0-12 UTC no aporta edge y el 00:00 es negativo.
WIN = (43200, 72000)

# Niveles reutilizables
OVERNIGHT = {"#StartHours#": 20, "#StartMinutes#": 0,
             "#EndHours#": 12, "#EndMinutes#": 0, "#Shift#": 1}
PREV_DAY = {"#Shift#": 1}
PREV_WEEK = {"#Shift#": 1}

EDGES = [
    {
        "slug": "01-overnight-low-cruce",
        "titulo": "Overnight low — cruce debajo",
        "nivel_bloque": "Prices.SessionLow",
        "nivel_params": OVERNIGHT,
        "nivel_desc": "mínimo del rango overnight (20:00 UTC del día previo → 12:00 UTC)",
        "comparador": "CrossesBelow",
        "evidencia": ("Exceso sobre el azar +0.0574 R/trade (el único de la matriz que pasa "
                      "los 5 filtros). n=675, 101/año. IS +0.090 / OOS +0.010 de exceso."),
    },
    {
        "slug": "02-prev-day-close-cierre",
        "titulo": "Cierre del día previo — cierra debajo",
        "nivel_bloque": "Prices.CloseD",
        "nivel_params": PREV_DAY,
        "nivel_desc": "cierre del día anterior",
        "comparador": "IsLower",
        "evidencia": ("Exceso +0.0181 R/trade, el más consistente entre mitades "
                      "(exceso IS +0.009 / OOS +0.035). n=1218, 182/año."),
    },
    {
        "slug": "03-prev-week-high-cruce",
        "titulo": "Máximo de la semana previa — cruce debajo",
        "nivel_bloque": "Prices.HighW",
        "nivel_params": PREV_WEEK,
        "nivel_desc": "máximo de la semana anterior",
        "comparador": "CrossesBelow",
        "evidencia": ("Exceso +0.1280 R/trade, el más alto de toda la matriz, pero el exceso "
                      "OOS es NEGATIVO (-0.121): probablemente sobreajuste de IS. n=198, 30/año. "
                      "Se genera justamente para verificar eso en el motor de SQ."),
    },
    {
        "slug": "04-overnight-high-retest",
        "titulo": "Overnight high — cruce debajo (rechazo)",
        "nivel_bloque": "Prices.SessionHigh",
        "nivel_params": OVERNIGHT,
        "nivel_desc": "máximo del rango overnight (20:00 → 12:00 UTC)",
        "comparador": "CrossesBelow",
        "evidencia": ("Exceso +0.0499 R/trade. n=825, 123/año. El cruce implica que el precio "
                      "venía por encima del máximo: es el patrón de rechazo/retest."),
    },
    {
        "slug": "05-overnight-high-cierre",
        "titulo": "Overnight high — cierra debajo",
        "nivel_bloque": "Prices.SessionHigh",
        "nivel_params": OVERNIGHT,
        "nivel_desc": "máximo del rango overnight (20:00 → 12:00 UTC)",
        "comparador": "IsLower",
        "evidencia": ("Exceso +0.0262 R/trade. n=1560, 233/año: la mayor frecuencia del set, "
                      "lo que da más base estadística aunque el exceso sea menor."),
    },
]


def profile_yaml(e: dict) -> str:
    return f"""# Builder generado automáticamente — edge: {e['titulo']}
#
# AÍSLA un único edge para poder probarlo en StrategyQuant. El catálogo de bloques
# queda reducido a tres: el nivel de referencia, el precio de cierre y el comparador.
# Con minConditions=1 el generador no puede armar reglas de otra familia.
#
# Nivel: {e['nivel_desc']}  ({e['nivel_bloque']})
# Evidencia medida (NAS100 H1, simulador propio con control de azar):
#   {e['evidencia']}
#
# ADVERTENCIA: el control de azar de ese mismo análisis da +0.139 R/trade en 12-20 UTC.
# Varios de estos edges tienen exceso cercano a cero, o sea que su R/trade absoluto es
# casi todo la expectativa propia del esquema de salida. Este builder sirve para que el
# motor de StrategyQuant —que es independiente del simulador propio— confirme o refute.
#
# Pasos manuales en la UI de SQ (lo que SQ revierte al guardar):
#   · Verificar el múltiplo del trailing stop (se busca ~1.5 ATR) en las opciones de salida.
#   · Reponer ExitAfterBars si SQ lo devuelve a 50.

name: {e['slug']}
description: "NAS100 H1 short-only — edge aislado: {e['titulo']}"

data:
  date_from: "2020-01-01"
  date_to: "2026-09-16"
  out_of_sample:
    - {{from: "2020-01-01", to: "2024-01-09", type: "isv"}}
    - {{from: "2024-01-09", to: "2026-09-16"}}

# Sin cap de RRR: el cap 60-120 exige win rates que estos setups (40-44%) no alcanzan.
# SL 2 ATR con trailing: esquema medido en el análisis.
risk_reward:
  limit_slpt_rrr: false
  sl_atr_multiple_min: 2.0
  sl_atr_multiple_max: 2.0

# Una sola condición: la entrada ES el quiebre del nivel.
entries:
  min_conditions: 1
  max_conditions: 2
  min_period: 5
  max_period: 100

trading:
  limit_time_range: true
  signal_time_from: {WIN[0]}
  signal_time_to: {WIN[1]}
  max_trades_per_day: 1
  max_open_positions_short: 1
  dont_trade_weekends: true
  exit_on_friday: true
  friday_exit_time: 75600

blocks:
  # Catálogo reducido: el comparador, el precio y el nivel. Nada más.
  set_signals: []
  set_indicators:
    - {e['comparador']}
    - Prices.Close
    - {e['nivel_bloque']}
  # Parámetros del nivel FIJADOS: sin esto el generador sortea las horas y el
  # nivel deja de representar lo que se quiere probar.
  fixed_params:
    {e['nivel_bloque']}:
{chr(10).join(f'      "{k}": {v}' for k, v in e['nivel_params'].items())}

# El fitness apunta directo a la métrica que el usuario quiere mejorar.
rankings:
  fitness: SQNScore
  sqn_score_min: 0.5
  number_of_trades_min: 100
  profit_factor_min: 1.1
  win_loss_ratio_min: 0.9
  rsquared_min: 0.4
  drawdown_pct_max: 25
  sample_type: 10

genetic:
  sqn_score_min: 0.3
  number_of_trades_min: 80
  profit_factor_min: 1.05
  sample_type: 10

exits:
  stop_loss_probability: 100
  trailing_stop_probability: 100
  profit_target_probability: 0
  exit_after_bars_probability: 100
"""


def main():
    resumen = []
    for e in EDGES:
        ppath = f"{PROF}/edge-{e['slug']}.yaml"
        with open(ppath, "w") as f:
            f.write(profile_yaml(e))
        opath = f"{OUT}/{e['slug']}.cfx"
        r = apply_builder_profile(TEMPLATE, opath, ppath)
        # verificación independiente del XML escrito
        z = zipfile.ZipFile(opath)
        xml = z.read("config.xml").decode("utf-8", errors="replace")
        on_ind = _on_blocks(xml, "indicators")
        on_sig = _on_blocks(xml, "signals")
        resumen.append({
            "edge": e["slug"], "cambios": r["applied"],
            "indicadores_on": on_ind, "señales_on": on_sig,
            "fijado": e["nivel_bloque"] in _fixed_blocks(xml), "bytes": len(xml),
        })
    print(f"{'edge':30s} {'cambios':>7s} {'indicadores activos':38s} {'señales':>7s} {'params fijados':>14s}")
    for x in resumen:
        print(f"{x['edge']:30s} {x['cambios']:7d} {str(x['indicadores_on'])[:38]:38s} "
              f"{len(x['señales_on']):7d} {str(x['fijado']):>14s}")


def _on_blocks(xml, cat):
    import re
    out = []
    for m in re.finditer(r'<Block key="([^"]+)"[^>]*category="' + cat + r'"[^>]*use="true"', xml):
        out.append(m.group(1))
    for m in re.finditer(r'<Block key="([^"]+)"[^>]*use="true"[^>]*category="' + cat + r'"', xml):
        out.append(m.group(1))
    return sorted(set(out))


def _fixed_blocks(xml):
    import re
    return set(re.findall(r'<Block key="([^"]+)"[^>]*>\s*<Generated.*?<Predefined changed="true">',
                          xml, re.S))


if __name__ == "__main__":
    main()
