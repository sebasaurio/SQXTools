"""Screener estadístico de señales de entrada.

Mide el **edge direccional real** de cada condición candidata sobre datos de mercado
reales, en vez de asumir que una señal "de tendencia" sirve para operar.

Metodología
-----------
Para cada condición booleana, evaluada con información hasta el cierre de la barra `t`:

  · retorno forward a `h` barras: ``close[t+h] / close[t] - 1``
  · para SHORTS un edge es un retorno forward NEGATIVO (y viceversa para longs)
  · el t-stat se corrige con **Newey-West** (lag = h-1) porque los retornos forward
    solapados están autocorrelacionados: sin la corrección el t-stat sale inflado y
    cualquier señal parece significativa
  · solo se evalúa dentro de la ventana operativa (`window_from`–`window_to` UTC)
  · se compara contra la línea base de la misma ventana (el "drift" del mercado)
  · se reporta la estabilidad In-Sample vs Out-of-Sample de cada señal

Lectura del resultado: `mean_fwd_pct` negativo + `p_value` bajo = condición útil
para shorts. `p_value` bajo + `mean_fwd_pct` positivo = la señal va EN CONTRA de
los shorts (es lo que ocurre con los filtros de volatilidad en un mercado que sube).

Uso programático:
    from sqxtools.signal_screen import screen
    res = screen(df, window_from=12, window_to=20, horizons=(4, 8, 24))
"""

from __future__ import annotations

from math import erfc, sqrt

import numpy as np
import pandas as pd

# Ventana operativa y horizontes por defecto (barras forward)
DEFAULT_WINDOW = (12, 20)
DEFAULT_HORIZONS = (4, 8, 24)
DEFAULT_MIN_N = 50


# ── Indicadores ──────────────────────────────────────────────────────────────
# Implementados a mano para no depender de TA-Lib y para que el screener pueda
# replicar la definición exacta de cada bloque de StrategyQuant.

def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def true_range(df: pd.DataFrame) -> pd.Series:
    pc = df["close"].shift()
    return pd.concat([
        df["high"] - df["low"],
        (df["high"] - pc).abs(),
        (df["low"] - pc).abs(),
    ], axis=1).max(axis=1)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    return true_range(df).ewm(alpha=1 / period, adjust=False).mean()


def adx_di(df: pd.DataFrame, period: int = 14):
    """Devuelve (ADX, DI+, DI-)."""
    up = df["high"].diff()
    dn = -df["low"].diff()
    plus_dm = np.where((up > dn) & (up > 0), up, 0.0)
    minus_dm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = true_range(df).ewm(alpha=1 / period, adjust=False).mean()
    pdi = 100 * pd.Series(plus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr
    mdi = 100 * pd.Series(minus_dm, index=df.index).ewm(alpha=1 / period, adjust=False).mean() / tr
    dx = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.ewm(alpha=1 / period, adjust=False).mean(), pdi, mdi


def bollinger(close: pd.Series, period: int = 20, dev: float = 2.0):
    ma = close.rolling(period).mean()
    sd = close.rolling(period).std()
    return ma, ma + dev * sd, ma - dev * sd


def stoch(df: pd.DataFrame, k: int = 14, d: int = 3, slowing: int = 3):
    ll = df["low"].rolling(k).min()
    hh = df["high"].rolling(k).max()
    raw = 100 * (df["close"] - ll) / (hh - ll).replace(0, np.nan)
    kk = raw.rolling(slowing).mean()
    return kk, kk.rolling(d).mean()


def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    hh = df["high"].rolling(period).max()
    ll = df["low"].rolling(period).min()
    return -100 * (hh - df["close"]) / (hh - ll).replace(0, np.nan)


def cci(df: pd.DataFrame, period: int = 20) -> pd.Series:
    tp = (df["high"] + df["low"] + df["close"]) / 3
    ma = tp.rolling(period).mean()
    md = (tp - ma).abs().rolling(period).mean()
    return (tp - ma) / (0.015 * md.replace(0, np.nan))


def aroon(df: pd.DataFrame, period: int = 14):
    """Devuelve (AroonUp, AroonDown)."""
    up = df["high"].rolling(period + 1).apply(lambda x: float(np.argmax(x)), raw=True)
    dn = df["low"].rolling(period + 1).apply(lambda x: float(np.argmin(x)), raw=True)
    return 100 * up / period, 100 * dn / period


def supertrend(df: pd.DataFrame, period: int = 10, mult: float = 3.0) -> pd.Series:
    """Devuelve +1 en tendencia alcista y -1 en bajista."""
    a = atr(df, period)
    hl2 = (df["high"] + df["low"]) / 2
    upper = (hl2 + mult * a).to_numpy()
    lower = (hl2 - mult * a).to_numpy()
    close = df["close"].to_numpy()
    n = len(df)
    trend = np.ones(n, dtype=int)
    fu = np.full(n, np.nan)
    fl = np.full(n, np.nan)
    for i in range(1, n):
        fu[i] = upper[i] if (np.isnan(fu[i - 1]) or upper[i] < fu[i - 1] or close[i - 1] > fu[i - 1]) else fu[i - 1]
        fl[i] = lower[i] if (np.isnan(fl[i - 1]) or lower[i] > fl[i - 1] or close[i - 1] < fl[i - 1]) else fl[i - 1]
        if np.isnan(fu[i]) or np.isnan(fl[i]):
            trend[i] = trend[i - 1]
        elif close[i] > fu[i - 1]:
            trend[i] = 1
        elif close[i] < fl[i - 1]:
            trend[i] = -1
        else:
            trend[i] = trend[i - 1]
    return pd.Series(trend, index=df.index)


def psar(df: pd.DataFrame, step: float = 0.02, maxaf: float = 0.2) -> pd.Series:
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    out = np.full(n, np.nan)
    bull, af, ep = True, step, high[0]
    sar = low[0]
    for i in range(1, n):
        sar = sar + af * (ep - sar)
        if bull:
            if low[i] < sar:
                bull, sar, ep, af = False, ep, low[i], step
            elif high[i] > ep:
                ep, af = high[i], min(af + step, maxaf)
        else:
            if high[i] > sar:
                bull, sar, ep, af = True, ep, high[i], step
            elif low[i] < ep:
                ep, af = low[i], min(af + step, maxaf)
        out[i] = sar
    return pd.Series(out, index=df.index)


def demarker(df: pd.DataFrame, period: int = 14) -> pd.Series:
    dmax = (df["high"] - df["high"].shift()).clip(lower=0)
    dmin = (df["low"].shift() - df["low"]).clip(lower=0)
    return dmax.ewm(alpha=1 / period, adjust=False).mean() / \
        (dmax + dmin).replace(0, np.nan).ewm(alpha=1 / period, adjust=False).mean()


def vwap_session(df: pd.DataFrame) -> pd.Series:
    """VWAP anclado al día UTC (reinicia en cada sesión)."""
    tp = (df["high"] + df["low"] + df["close"]) / 3
    vol = df["volume"].replace(0, np.nan)
    day = df["timestamp"].dt.floor("D")
    return (tp * vol).groupby(day).cumsum() / vol.groupby(day).cumsum()


def keltner(df: pd.DataFrame, period: int = 20, mult: float = 1.5):
    """Devuelve (banda superior, banda inferior)."""
    ema = df["close"].ewm(span=period, adjust=False).mean()
    a = atr(df, period)
    return ema + mult * a, ema - mult * a


def ulcer_index(close: pd.Series, period: int = 14) -> pd.Series:
    roll_max = close.rolling(period).max()
    pct_dd = 100 * (close - roll_max) / roll_max.replace(0, np.nan)
    return np.sqrt((pct_dd ** 2).rolling(period).mean())


def laguerre_rsi(close: pd.Series, gamma: float = 0.7) -> pd.Series:
    n = len(close)
    c = close.to_numpy()
    out = np.full(n, np.nan)
    l0 = l1 = l2 = l3 = 0.0
    for i in range(1, n):
        l0n = (1 - gamma) * c[i] + gamma * l0
        l1n = -gamma * l0n + l0 + gamma * l1
        l2n = -gamma * l1n + l1 + gamma * l2
        l3n = -gamma * l2n + l2 + gamma * l3
        l0, l1, l2, l3 = l0n, l1n, l2n, l3n
        cu = (l0 > l1) * (l1 > l2) * (l2 > l3) * (l0 - l3)
        cd = (l0 < l1) * (l1 < l2) * (l2 < l3) * (l3 - l0)
        denom = cu + cd
        out[i] = 100 * cu / denom if denom != 0 else (out[i - 1] if i else 50.0)
    return pd.Series(out, index=close.index)


def wave_trend(df: pd.DataFrame, channel: int = 10, average: int = 21):
    """Devuelve (WaveTrend, media de WaveTrend)."""
    ap = (df["high"] + df["low"] + df["close"]) / 3
    esa = ap.ewm(span=channel, adjust=False).mean()
    d = (ap - esa).abs().ewm(span=channel, adjust=False).mean()
    ci = (ap - esa) / (0.015 * d.replace(0, np.nan))
    wt1 = ci.ewm(span=average, adjust=False).mean()
    return wt1, wt1.rolling(4).mean()


def schaff_trend_cycle(close: pd.Series, stoch_len: int = 10,
                       fast: int = 23, slow: int = 50) -> pd.Series:
    macd = close.ewm(span=fast, adjust=False).mean() - close.ewm(span=slow, adjust=False).mean()
    ll, hh = macd.rolling(stoch_len).min(), macd.rolling(stoch_len).max()
    st = 100 * (macd - ll) / (hh - ll).replace(0, np.nan)
    k = st.fillna(50).ewm(span=3, adjust=False).mean()
    return k.ewm(span=3, adjust=False).mean()


def qqe(close: pd.Series, period: int = 14, smooth: int = 5):
    """Devuelve (QQE, banda superior, banda inferior)."""
    r = rsi(close, period).ewm(span=smooth, adjust=False).mean()
    dar = r.diff().abs().ewm(span=period, adjust=False).mean() * 4.236
    return r, r + dar, r - dar


# ── Catálogo de condiciones candidatas ───────────────────────────────────────

def build_conditions(df: pd.DataFrame) -> dict[str, dict[str, pd.Series]]:
    """Construye el catálogo de condiciones candidatas agrupadas por familia."""
    close, high, low, op = df["close"], df["high"], df["low"], df["open"]
    r14 = rsi(close, 14)
    a14 = atr(df, 14)
    adx, pdi, mdi = adx_di(df)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    macd_sig = macd.ewm(span=9, adjust=False).mean()
    ma20, bbu, bbl = bollinger(close)
    kk, dd = stoch(df)
    wr = williams_r(df)
    cc = cci(df)
    au, ad = aroon(df)
    st = supertrend(df)
    sar = psar(df)
    dm = demarker(df)
    vw = vwap_session(df)
    kcu, kcl = keltner(df)
    ui = ulcer_index(close)
    lrsi = laguerre_rsi(close)
    wt1, _ = wave_trend(df)
    stc = schaff_trend_cycle(close)
    qline, _, _ = qqe(close)
    vol_ma = df["volume"].rolling(20).mean()
    atr_ma = a14.rolling(20).mean()
    bw = (bbu - bbl) / ma20
    up_run = (close.diff() > 0).astype(int)

    def consecutive_up(n: int) -> pd.Series:
        s = up_run.copy()
        for k in range(1, n):
            s = s + up_run.shift(k)
        return s == n

    return {
        "tendencia": {
            "SuperTrendDownTrend": st < 0,
            "PSARBarLower (SAR sobre el precio)": sar > close,
            "Precio bajo SMA20": close < ma20,
            "SMA20 cayendo": ma20.diff() < 0,
            "AroonDown > 70": ad > 70,
            "AroonDownRiseFromBottom": (ad > ad.shift(3)) & (ad.shift(3) < 30),
            "AroonFallFromTop": (au < au.shift(3)) & (au.shift(3) > 70),
            "Nuevo mínimo de 20 barras": close <= low.rolling(20).min(),
        },
        "fuerza": {
            "ADXHigher (>25)": adx > 25,
            "ADXLower (<20, rango)": adx < 20,
            "ADXRising": adx > adx.shift(3),
            "DI- > DI+": mdi > pdi,
            "DI- subiendo": mdi > mdi.shift(3),
            "ADX>25 y DI->DI+": (adx > 25) & (mdi > pdi),
            "Bajo SMA20 y ADX>25": (close < ma20) & (adx > 25),
        },
        "momentum": {
            "RSIFalling": r14 < r14.shift(1),
            "RSILower (<30)": r14 < 30,
            "RSI en 30-50": (r14 >= 30) & (r14 < 50),
            "MACDMainCrossBelowZero": (macd < 0) & (macd.shift(1) >= 0),
            "MACD bajo cero": macd < 0,
            "MACDSignalFalling": macd_sig < macd_sig.shift(1),
            "StochSlowDCrossDown": (dd < kk) & (dd.shift(1) >= kk.shift(1)),
            "WPRFalling": wr < wr.shift(1),
            "CCIChangesDown": (cc < cc.shift(1)) & (cc.shift(1) > 0),
            "DeMarker > 0.7": dm > 0.7,
            "LaguerreRSIFalling": lrsi < lrsi.shift(1),
            "QQE bajando": qline < qline.shift(1),
            "SchaffTrendCycle baja de 50": (stc < 50) & (stc.shift(1) >= 50),
            "WaveTrendMainFalling": wt1 < wt1.shift(1),
        },
        "volatilidad": {
            "ATRRising": a14 > a14.shift(3),
            "ATR sobre su media": a14 > atr_ma,
            "BBUpperFalling": bbu < bbu.shift(1),
            "BBLowerFalling": bbl < bbl.shift(1),
            "BB anchas (bandwidth alto)": bw > bw.rolling(100).mean(),
            "UlcerIndex alto": ui > ui.rolling(100).mean(),
        },
        "volumen": {
            "VolumeRising": df["volume"] > df["volume"].shift(1),
            "Volumen sobre la media": df["volume"] > vol_ma,
            "Volumen 1.5x la media": df["volume"] > 1.5 * vol_ma,
        },
        "vwap": {
            "CloseBelowVWAP": close < vw,
            "VWAPFalling": vw < vw.shift(3),
            "Precio bajo VWAP y VWAP cayendo": (close < vw) & (vw < vw.shift(3)),
        },
        "velas": {
            "Doji": ((close - low) < 0.25 * (high - low)) & ((high - close) < 0.25 * (high - low)),
            "ShootingStar (mecha sup. larga)": (high - close) > 0.6 * (high - low),
            "BearishEngulfing": (close < op) & (close.shift(1) > op.shift(1)) &
                                (close < op.shift(1)) & (op > close.shift(1)),
            "DarkCloud": (close.shift(1) > op.shift(1)) & (op > close.shift(1)) &
                         (close < (close.shift(1) + op.shift(1)) / 2),
            "Gap alcista (open > high previo)": op > high.shift(1),
        },
        "extension": {
            "RSI > 70 (sobrecompra)": r14 > 70,
            "RSI > 75 (extremo)": r14 > 75,
            "Stoch %K > 90": kk > 90,
            "WPR > -10 (extremo)": wr > -10,
            "CCI > 150": cc > 150,
            "DeMarker > 0.8": dm > 0.8,
            "Close > BB superior": close > bbu,
            "Precio > 2 ATR sobre SMA20": close > ma20 + 2 * a14,
            "Precio > 1.5 ATR sobre VWAP": close > vw + 1.5 * a14,
            "3 barras alcistas seguidas": consecutive_up(3),
            "4 barras alcistas seguidas": consecutive_up(4),
            "Ret 8 barras > +1%": close / close.shift(8) - 1 > 0.01,
            "Ret 24 barras > +2%": close / close.shift(24) - 1 > 0.02,
        },
        "canales": {
            "Precio bajo Keltner inferior": close < kcl,
            "KeltnerUpperFalling": kcu < kcu.shift(1),
        },
    }


def flatten_conditions(df: pd.DataFrame) -> list[tuple[str, str, pd.Series]]:
    """Catálogo aplanado: lista de (familia, nombre, condición)."""
    out = []
    for fam, group in build_conditions(df).items():
        for name, cond in group.items():
            out.append((fam, name, cond))
    return out


# ── Estadística ──────────────────────────────────────────────────────────────

def nw_tstat(x, lag: int) -> float:
    """t-stat de la media con corrección Newey-West (retornos solapados).

    Los retornos forward a `h` barras se solapan entre barras consecutivas, lo que
    induce autocorrelación y **infla** el t-stat. NW con lag = h-1 lo corrige.
    """
    x = np.asarray(x, dtype=float)
    n = len(x)
    if n < 3:
        return 0.0
    m = x.mean()
    d = x - m
    S = float(d @ d) / n
    for j in range(1, min(lag, n - 1) + 1):
        S += 2 * (1 - j / (lag + 1)) * float(d[j:] @ d[:-j]) / n
    return m / sqrt(S / n) if S > 0 else 0.0


def p_value(t: float) -> float:
    """p-valor de dos colas (aprox. normal; válido para n > ~20)."""
    return erfc(abs(t) / sqrt(2))


def evaluate_signal(cond: pd.Series, fwd: pd.Series, horizon: int,
                    min_n: int = DEFAULT_MIN_N) -> dict | None:
    """Métricas de una condición sobre un horizonte forward. None si no hay muestra."""
    mask = cond.fillna(False).to_numpy() & fwd.notna().to_numpy()
    n = int(mask.sum())
    if n < min_n:
        return None
    x = fwd.to_numpy()[mask]
    mean = float(x.mean())
    t = nw_tstat(x, horizon - 1)
    return {"n": n, "mean_fwd_pct": 100 * mean, "t_stat": t, "p_value": p_value(t)}


def _baseline(fwd: pd.Series) -> dict:
    x = fwd.dropna().to_numpy()
    if len(x) < 10:
        return {"n": int(len(x)), "mean_fwd_pct": None, "t_stat": None, "p_value": None}
    mean = float(x.mean())
    t = nw_tstat(x, 0)
    return {"n": int(len(x)), "mean_fwd_pct": 100 * mean, "t_stat": t, "p_value": p_value(t)}


def screen(df: pd.DataFrame, window_from: int = DEFAULT_WINDOW[0],
           window_to: int = DEFAULT_WINDOW[1],
           horizons=DEFAULT_HORIZONS, min_n: int = DEFAULT_MIN_N,
           direction: str = "short", split: float = 0.6) -> dict:
    """Mide el edge de todas las condiciones candidatas.

    Args:
        window_from/window_to: ventana horaria UTC en la que se permite la entrada.
        horizons: horizontes forward en barras.
        min_n: muestra mínima para reportar una condición.
        direction: 'short' (edge = retorno negativo) o 'long' (edge = positivo).
        split: fracción del período usada como In-Sample para el contraste IS/OOS.

    Returns:
        Dict serializable con baseline, resultados por señal y destacados.
    """
    if direction not in ("short", "long"):
        raise ValueError("direction debe ser 'short' o 'long'")
    if not 0.05 < split < 0.95:
        raise ValueError("split debe estar entre 0.05 y 0.95")

    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    df = df.sort_values("timestamp").reset_index(drop=True)
    hour = df["timestamp"].dt.hour
    in_window = (hour >= window_from) & (hour <= window_to)
    close = df["close"]

    cut = df["timestamp"].quantile(split)
    is_mask = df["timestamp"] <= cut

    fwd = {h: close.shift(-h) / close - 1 for h in horizons}
    baseline = {h: _baseline(fwd[h][in_window]) for h in horizons}

    results: list[dict] = []
    for fam, name, cond in flatten_conditions(df):
        cond_w = cond & in_window
        for h in horizons:
            res = evaluate_signal(cond_w, fwd[h], h, min_n)
            if res is None:
                continue
            is_res = evaluate_signal(cond_w & is_mask, fwd[h], h, max(min_n // 2, 15))
            oos_res = evaluate_signal(cond_w & ~is_mask, fwd[h], h, max(min_n // 2, 15))
            mean = res["mean_fwd_pct"]
            edge = -mean if direction == "short" else mean
            results.append({
                "familia": fam, "senal": name, "horizonte": h,
                "n": res["n"], "mean_fwd_pct": mean,
                "edge_pct": edge,
                "t_stat": res["t_stat"], "p_value": res["p_value"],
                "significativa": res["p_value"] < 0.05,
                "favorable": edge > 0,
                "base_mean_pct": baseline[h]["mean_fwd_pct"],
                "is_mean_pct": is_res["mean_fwd_pct"] if is_res else None,
                "is_p": is_res["p_value"] if is_res else None,
                "oos_mean_pct": oos_res["mean_fwd_pct"] if oos_res else None,
                "oos_p": oos_res["p_value"] if oos_res else None,
            })

    # Con ~45 señales × horizontes, a p<0.05 se esperan varios falsos positivos por
    # azar. Solo se destacan las que además sobreviven en IS y OOS con el mismo signo.
    def _consistent(r: dict) -> bool:
        if r["is_mean_pct"] is None or r["oos_mean_pct"] is None:
            return False
        is_edge = -r["is_mean_pct"] if direction == "short" else r["is_mean_pct"]
        oos_edge = -r["oos_mean_pct"] if direction == "short" else r["oos_mean_pct"]
        return is_edge > 0 and oos_edge > 0

    edge_real = sorted((r for r in results if r["favorable"] and r["significativa"]),
                       key=lambda r: -r["edge_pct"])
    contra = sorted((r for r in results if not r["favorable"] and r["significativa"]),
                    key=lambda r: r["edge_pct"])
    robustas = [r for r in edge_real if _consistent(r)]

    return {
        "data_info": {
            "barras": int(len(df)),
            "desde": str(df["timestamp"].iloc[0]),
            "hasta": str(df["timestamp"].iloc[-1]),
            "años": round((df["timestamp"].iloc[-1] - df["timestamp"].iloc[0]).days / 365.25, 1),
        },
        "config": {"window": [window_from, window_to], "horizons": list(horizons),
                   "min_n": min_n, "direction": direction, "split": split,
                   "corte_is_oos": str(cut)},
        "baseline": {f"h{h}": v for h, v in baseline.items()},
        "resultados": results,
        "destacados": {
            "edge_robusto_is_oos": robustas,
            "edge_significativo": edge_real,
            "en_contra_de_la_direccion": contra[:10],
        },
        "notas": [
            "t-stat con corrección Newey-West (lag = h-1) por solapamiento de retornos.",
            f"Con {len(results)} pruebas, a p<0.05 se esperan ~{0.05*len(results):.0f} falsos "
            "positivos: solo 'edge_robusto_is_oos' exige consistencia IS y OOS.",
            "Un edge menor al costo de transacción (spread + slippage) no es operable.",
        ],
    }
