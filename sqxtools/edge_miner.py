"""Minero de edges: matriz de NIVELES de referencia × TIPOS de disparo.

Nace de lo medido en `analysis/build_shorts_report.py`:

- Lo que funcionaba era siempre la misma mecánica → **quiebre de un nivel de
  referencia + trailing stop** (ORB, mínimo del día previo, NR7).
- Lo que fallaba era vender fuerza (mean reversion) o patrones sin nivel.

Entonces, en vez de inventar indicadores nuevos, se **sistematiza** lo que
funcionaba: se cruzan muchos niveles (rango de apertura, balance inicial,
niveles del día/semana previos, rango overnight, VWAP y sus bandas) con varios
tipos de disparo (cierre más allá, cruce, retest-rechazo) y se mide cada celda.

Cada candidato pasa por **cuatro filtros de robustez** antes de considerarse edge:

1. **Muestra**: n ≥ 100 trades.
2. **Consistencia temporal**: R/trade > 0 en In-Sample **y** en Out-of-Sample.
3. **Estabilidad de parámetro**: positivo con al menos 3 de 4 distancias de trailing
   (una celda que solo funciona con un valor exacto está ajustada).
4. **Especificidad direccional**: el espejo long de la misma condición NO debe ser
   rentable. Si ambas direcciones ganan, no es un edge direccional sino un artefacto
   de la mecánica de salida.

Con ~40 celdas evaluadas, el filtro 2 solo ya deja pasar ~10 por azar; los filtros
3 y 4 son los que separan señal de ruido. Aun así, cualquier resultado debe tratarse
como hipótesis a validar, no como certeza.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .edge_backtest import simulate, stats
from .signal_screen import atr, vwap_session

TRAILS = (1.0, 1.5, 2.0, 2.5)
SL_MULT = 2.0
HOLD = 24

# Hora UTC desde la cual cada nivel está **realmente formado** y puede usarse como
# entrada. Un nivel disponible antes de esta hora contamina el test con lookahead.
# El rango de apertura usa la barra de las 13:00 → se conoce al cerrar las 14:00.
# El balance inicial usa 13:00+14:00 → se conoce al cerrar las 15:00.
LEVELS_MIN_HOUR = {
    "ORB low (13h)": 14,
    "ORB high (13h)": 14,
    "Session open (13h)": 14,
    "IB low (13-14h)": 15,
    "IB high (13-14h)": 15,
    "Overnight low": 13,
    "Overnight high": 13,
    "VWAP": 13,
    "VWAP - 1σ": 13,
    "VWAP + 1σ": 13,
    "Prev-day low": 0,
    "Prev-day high": 0,
    "Prev-day close": 0,
    "Prev-week low": 0,
    "Prev-week high": 0,
}


# ── Niveles de referencia ────────────────────────────────────────────────────

def _session_key(ts: pd.Series) -> pd.Series:
    """Clave de 'día de sesión': el día corre de 20:00 UTC al día siguiente 19:59.

    Así el rango overnight (20:00→12:59) y la sesión (13:00→19:59) caen en la
    misma clave y se pueden agregar juntos.
    """
    return (ts + pd.Timedelta(hours=4)).dt.date


def build_levels(df: pd.DataFrame) -> dict[str, np.ndarray]:
    """Niveles de referencia, cada uno NaN hasta el momento en que **realmente se conoce**.

    La causalidad se maneja con `LEVELS_MIN_HOUR`: un nivel formado dentro de la
    sesión (el rango de apertura, el balance inicial) NO puede estar disponible
    para las barras anteriores a su formación. Dejarlo visible para todo el día
    introduce lookahead y produce resultados espectaculares y falsos.
    """
    ts = df["timestamp"]
    hour = ts.dt.hour.to_numpy()
    key = _session_key(ts)
    low, high, close, op = (df[c].to_numpy() for c in ("low", "high", "close", "open"))
    vw = np.asarray(vwap_session(df), dtype=float)
    in_session = (hour >= 13) & (hour <= 19)

    def by_key(mask, values, how, min_hour):
        """Agrega por sesión y devuelve el valor solo desde `min_hour`."""
        s = pd.Series(np.where(mask, values, np.nan)).groupby(key.to_numpy()).agg(how)
        out = s.reindex(key.to_numpy()).to_numpy()
        return np.where((hour >= min_hour) & in_session, out, np.nan)

    overnight = (hour >= 20) | (hour <= 12)
    first_hour = hour == 13
    ib = (hour == 13) | (hour == 14)

    levels: dict[str, np.ndarray] = {}
    levels["ORB low (13h)"] = by_key(first_hour, low, "min", LEVELS_MIN_HOUR["ORB low (13h)"])
    levels["ORB high (13h)"] = by_key(first_hour, high, "max", LEVELS_MIN_HOUR["ORB high (13h)"])
    levels["IB low (13-14h)"] = by_key(ib, low, "min", LEVELS_MIN_HOUR["IB low (13-14h)"])
    levels["IB high (13-14h)"] = by_key(ib, high, "max", LEVELS_MIN_HOUR["IB high (13-14h)"])
    levels["Overnight low"] = by_key(overnight, low, "min", LEVELS_MIN_HOUR["Overnight low"])
    levels["Overnight high"] = by_key(overnight, high, "max", LEVELS_MIN_HOUR["Overnight high"])
    levels["Session open (13h)"] = by_key(first_hour, op, "max", LEVELS_MIN_HOUR["Session open (13h)"])

    # VWAP y bandas: causales (cumsum intradía / rolling pasado)
    sig = df["close"].rolling(20).std().to_numpy()
    levels["VWAP"] = np.where(hour >= LEVELS_MIN_HOUR["VWAP"], vw, np.nan)
    levels["VWAP - 1σ"] = np.where(hour >= LEVELS_MIN_HOUR["VWAP - 1σ"],
                                   vw - np.r_[np.nan, sig[:-1]], np.nan)
    levels["VWAP + 1σ"] = np.where(hour >= LEVELS_MIN_HOUR["VWAP + 1σ"],
                                   vw + np.r_[np.nan, sig[:-1]], np.nan)

    # Niveles diarios / semanales previos: conocidos desde el arranque del día
    day = ts.dt.floor("D")
    d1 = df.set_index("timestamp").resample("1D").agg(
        {"high": "max", "low": "min", "close": "last"}).dropna()
    levels["Prev-day low"] = d1["low"].shift(1).reindex(day).ffill().to_numpy()
    levels["Prev-day high"] = d1["high"].shift(1).reindex(day).ffill().to_numpy()
    levels["Prev-day close"] = d1["close"].shift(1).reindex(day).ffill().to_numpy()

    w = df.groupby(ts.dt.tz_localize(None).dt.to_period("W")).agg(
        wl=("low", "min"), wh=("high", "max")).shift(1)
    wk = ts.dt.tz_localize(None).dt.to_period("W")
    levels["Prev-week low"] = w["wl"].reindex(wk.to_numpy()).to_numpy()
    levels["Prev-week high"] = w["wh"].reindex(wk.to_numpy()).to_numpy()

    return levels


def triggers(level: np.ndarray, close: np.ndarray, high: np.ndarray,
             low: np.ndarray, prev_close: np.ndarray) -> dict[str, np.ndarray]:
    """Tipos de disparo para un nivel dado (condición de SHORT)."""
    lv = np.asarray(level, dtype=float)
    below = close < lv
    cross = (prev_close >= lv) & below
    # retest: tocó el nivel desde abajo en las últimas 3 barras y cierra debajo
    touched = np.zeros_like(below)
    for k in range(1, 4):
        touched |= (pd.Series(high).shift(k).to_numpy() >= lv) & (pd.Series(close).shift(k).to_numpy() < lv)
    retest = touched & below
    return {
        "cierre debajo": below,
        "cruce debajo": cross,
        "retest+rechazo": retest,
    }


# ── Minería ──────────────────────────────────────────────────────────────────

def _prep(df: pd.DataFrame) -> dict:
    """Arrays y niveles compartidos por las funciones de análisis."""
    ts = df["timestamp"]
    return {
        "ts": ts,
        "hour": ts.dt.hour.to_numpy(),
        "day": ts.dt.floor("D"),
        "close": df["close"].to_numpy(),
        "high": df["high"].to_numpy(),
        "low": df["low"].to_numpy(),
        "a14": atr(df, 14).to_numpy(),
        "prev_close": np.r_[np.nan, df["close"].to_numpy()[:-1]],
        "levels": build_levels(df),
        "is_mask": (ts <= ts.iloc[int(len(ts) * 0.6)]).to_numpy(),
    }


def entries_for(p: dict, level_name: str, trigger_name: str,
                window: tuple[int, int] | None = None) -> np.ndarray:
    """Barras de entrada para una celda nivel × disparo (máx. 1 por día)."""
    masks = triggers(p["levels"][level_name], p["close"], p["high"],
                     p["low"], p["prev_close"])
    mask = np.asarray(masks[trigger_name], bool)
    if window is not None:
        mask &= (p["hour"] >= window[0]) & (p["hour"] <= window[1])
    seen, keep = set(), []
    for i in np.flatnonzero(mask):
        if i >= len(p["a14"]):
            continue
        if p["day"].iloc[i] not in seen and np.isfinite(p["a14"][i]) and p["a14"][i] > 0:
            seen.add(p["day"].iloc[i])
            keep.append(i)
    return np.array(keep, dtype=int)


def hourly_profile(df: pd.DataFrame, level_name: str, trigger_name: str) -> pd.DataFrame:
    """R/trade por hora de entrada — muestra dónde vive realmente el edge.

    Se calcula con la ventana ABIERTA (24h) para no presuponer horario. Es la
    vista honesta: si el edge está concentrado en 1-2 horas, es frágil; si está
    repartido, la ventana se puede elegir por conveniencia operativa.
    """
    p = _prep(df)
    ent = entries_for(p, level_name, trigger_name, window=None)
    if not len(ent):
        return pd.DataFrame()
    r = simulate(ent, p["close"], p["high"], p["low"], p["a14"], sl_mult=SL_MULT,
                 pt_mult=None, trail_mult=1.5, hold=HOLD,
                 window_mask=np.ones(len(p["close"]), bool))
    if not len(r):
        return pd.DataFrame()
    h = p["hour"][ent]
    rows = []
    for hh in range(24):
        sel = h == hh
        if sel.sum() == 0:
            continue
        rows.append({
            "hora_utc": hh, "n": int(sel.sum()),
            "R/trade": round(float(r[sel].mean()), 3),
            "% del total": f"{sel.sum() / len(ent) * 100:.1f}%",
            "R aportado": round(float(r[sel].sum()), 1),
            "todo o nada": bool((r[sel] > 0).all() or (r[sel] < 0).all()),
        })
    return pd.DataFrame(rows)


DEFAULT_WINDOWS = [
    ("24h (sin filtro)", None),
    ("12-20 (actual)", (12, 20)),
    ("13-19 (sesión NY)", (13, 19)),
    ("14-20", (14, 20)),
    ("15-20", (15, 20)),
    ("8-20 (Europa+NY)", (8, 20)),
    ("8-22 (extendido)", (8, 22)),
    ("0-12 (Asia/overnight)", (0, 12)),
    ("20-23 (post-cierre)", (20, 23)),
]


def scan_windows(df: pd.DataFrame, cells: list[tuple[str, str]],
                 windows: list | None = None) -> pd.DataFrame:
    """Evalúa cada celda en cada ventana horaria, con IS/OOS para detectar sobreajuste.

    Elegir la ventana mirando el resultado del período completo es una forma de
    sobreajuste: por eso acá se exige que funcione en In-Sample Y en Out-of-Sample.
    Una ventana que solo gana en el total pero pierde en IS no es elegible.
    """
    p = _prep(df)
    rows = []
    for lname, tname in cells:
        for label, w in (windows or DEFAULT_WINDOWS):
            ent = entries_for(p, lname, tname, window=w)
            if len(ent) < 40:
                continue
            r = simulate(ent, p["close"], p["high"], p["low"], p["a14"], sl_mult=SL_MULT,
                         pt_mult=None, trail_mult=1.5, hold=HOLD,
                         window_mask=np.ones(len(p["close"]), bool))
            if not len(r):
                continue
            is_in = p["is_mask"][ent][:len(r)]
            rows.append({
                "celda": f"{lname} / {tname}", "ventana": label, "n": len(r),
                "win%": round(float((r > 0).mean() * 100), 1),
                "R/trade": round(float(r.mean()), 4),
                "IS": round(float(r[is_in].mean()), 4) if is_in.sum() else None,
                "OOS": round(float(r[~is_in].mean()), 4) if (~is_in).sum() else None,
            })
    return pd.DataFrame(rows)


def random_baseline(df: pd.DataFrame, window: tuple[int, int] | None = (12, 20),
                    long: bool = False, prep: dict | None = None) -> float:
    """R/trade de entrar **al azar** 1 vez por día con la MISMA mecánica de salida.

    Es el control que faltaba: la combinación SL 2 ATR + trailing 1.5 ATR + hold 24
    tiene expectativa positiva propia en NAS100 H1 (el mercado tiende a moverse durante
    la sesión). Sin este control, cualquier señal que dispare en horas de volatilidad
    parece un edge: el ORB breakdown daba +0.143 contra una base de +0.139.

    La entrada se toma en la primera barra disponible de cada día dentro de la ventana
    (determinista, sin azar real) para que el número sea reproducible.
    """
    p = prep or _prep(df)
    win = np.ones(len(p["close"]), bool) if window is None else \
        ((p["hour"] >= window[0]) & (p["hour"] <= window[1]))
    seen, ent = set(), []
    for i in np.flatnonzero(win):
        d = p["day"].iloc[i]
        if d in seen or not np.isfinite(p["a14"][i]) or p["a14"][i] <= 0:
            continue
        seen.add(d)
        ent.append(i)
    if not ent:
        return float("nan")
    r = simulate(np.array(ent), p["close"], p["high"], p["low"], p["a14"], long=long,
                 sl_mult=SL_MULT, pt_mult=None, trail_mult=1.5, hold=HOLD,
                 window_mask=np.ones(len(p["close"]), bool))
    return float(r.mean()) if len(r) else float("nan")


def mine(df: pd.DataFrame, window: tuple[int, int] | None = (12, 20),
         is_split: float = 0.6, min_n: int = 100) -> pd.DataFrame:
    """Evalúa la matriz nivel × disparo y devuelve la tabla de resultados.

    `window=None` desactiva el filtro horario (24h). Los niveles de sesión se
    autolimitan igual, porque son NaN fuera de su ventana de disponibilidad;
    los niveles de día/semana previos sí se pueden operar a cualquier hora.
    """
    ts = df["timestamp"]
    hour = ts.dt.hour.to_numpy()
    close = df["close"].to_numpy()
    high = df["high"].to_numpy()
    low = df["low"].to_numpy()
    a14 = atr(df, 14).to_numpy()
    win = np.ones(len(df), bool) if window is None else ((hour >= window[0]) & (hour <= window[1]))
    split_ts = ts.iloc[int(len(ts) * is_split)]
    is_mask = (ts <= split_ts).to_numpy()
    day = ts.dt.floor("D")
    prev_close = np.r_[np.nan, close[:-1]]

    levels = build_levels(df)
    rows = []
    for lname, lv in levels.items():
        if np.all(~np.isfinite(lv)):
            continue
        for tname, mask in triggers(lv, close, high, low, prev_close).items():
            entries_all = np.flatnonzero(np.asarray(mask, bool) & win)
            # una entrada por día
            seen, ent = set(), []
            for i in entries_all:
                if day.iloc[i] not in seen and np.isfinite(a14[i]) and a14[i] > 0:
                    seen.add(day.iloc[i])
                    ent.append(i)
            ent = np.array(ent, dtype=int)
            if len(ent) < min_n:
                continue

            def run(idx, trail, long=False):
                return simulate(idx, close, high, low, a14, long=long,
                                sl_mult=SL_MULT, pt_mult=None, trail_mult=trail,
                                hold=HOLD, window_mask=win)

            r = run(ent, 1.5)
            r_is = run(ent[is_mask[ent]], 1.5)
            r_oos = run(ent[~is_mask[ent]], 1.5)
            if len(r) == 0:
                continue
            per_trail = {t: run(ent, t) for t in TRAILS}
            r_long = run(ent, 1.5, long=True)          # espejo: no debería ganar
            s = stats(r, ts.iloc[ent].values)
            pos_trails = sum(1 for t in TRAILS if len(per_trail[t]) and per_trail[t].mean() > 0)
            rows.append({
                "nivel": lname, "disparo": tname, "n": len(r),
                "por_año": round(len(r) / 6.7, 0),
                "win%": s["win_pct"], "R_short": round(r.mean(), 4),
                "IS": round(r_is.mean(), 4) if len(r_is) else None,
                "OOS": round(r_oos.mean(), 4) if len(r_oos) else None,
                "trails_positivos": f"{pos_trails}/{len(TRAILS)}",
                "R_long_espejo": round(r_long.mean(), 4) if len(r_long) else None,
                "años+": s.get("positive_years"),
                "max_dd": s["max_dd"],
                "mejor_año%": s.get("best_year_share_pct"),
            })
    t = pd.DataFrame(rows)
    if not len(t):
        return t
    # Control de azar: mismo esquema de salida, entrada en la primera barra del día.
    p = _prep(df)
    t["R_base"] = random_baseline(df, window, prep=p)
    t["espejo_base"] = random_baseline(df, window, long=True, prep=p)
    for half, name in ((p["is_mask"], "IS"), (~p["is_mask"], "OOS")):
        sub = df[half]
        t[f"{name}_base"] = random_baseline(sub, window, prep=_prep(sub))
    t["exceso"] = t["R_short"] - t["R_base"]
    t["exceso_IS"] = t["IS"] - t["IS_base"]
    t["exceso_OOS"] = t["OOS"] - t["OOS_base"]
    t["espejo_vs_base"] = t["R_long_espejo"] - t["espejo_base"]
    return t.sort_values("exceso", ascending=False).reset_index(drop=True)


def apply_gates(t: pd.DataFrame) -> pd.DataFrame:
    """Aplica los filtros de robustez y agrega la columna `gates`.

    El filtro central es **superar al azar**: `exceso = R_short - R_base`, donde la
    base es entrar en la primera barra del día con el mismo esquema de salida. Sin
    este control, un edge que dispare en horas volátiles parece rentable cuando en
    realidad solo está cosechando la expectativa propia del esquema de salida.
    """
    def passed(row):
        g = []
        if row["n"] >= 100:
            g.append("muestra")
        if row.get("exceso", 0) > 0:
            g.append(">azar")
        if row.get("exceso_IS", -1) > 0 and row.get("exceso_OOS", -1) > 0:
            g.append("IS+OOS")
        if row["trails_positivos"].startswith(("4", "3")):
            g.append("estable")
        if row.get("espejo_vs_base", 1) <= 0:
            g.append("direccional")
        return g

    t = t.copy()
    t["gates"] = t.apply(passed, axis=1)
    t["n_gates"] = t["gates"].apply(len)
    return t.sort_values(["n_gates", "exceso"], ascending=False).reset_index(drop=True)
