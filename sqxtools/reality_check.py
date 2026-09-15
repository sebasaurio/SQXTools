"""Reality-check: cruza lo que SQX va a modelar con lo que el broker ejecuta realmente.

Fuentes:
  - specs CSV del broker   (mt5-sync → sqx_specs.csv)      spread/tick/swaps reales
  - sesiones CSV del broker (mt5-sessions → sqx_sessions.csv) horarios reales por día
  - un .cfx builder y/o un Custom Project (.cfx multi-task)

Detecta contradicciones que, vistas tarde, cuestan builds enteros:
  1. spread_vs_mc          spread real vs rango RandomizeSpread del MC-Retest
  2. min_pt_vs_spread      el PT mínimo deja margen neto tras el spread
  3. ventana_vs_sesion     la ventana horaria del builder está dentro de la sesión real
  4. time_stop_vs_sesion   el ExitAfterBars cabe en la sesión sin cruzar el cierre
  5. swap_direccion        estrategia direccional vs swap del lado que opera
  6. breakeven_con_costos  win rate de breakeven real (RRR + spread), no el teórico
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .parser import parse_cfx

DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]


def _norm(n: str) -> str:
    prev = None
    while prev != n:
        prev = n
        n = re.sub(r"(_exness|[mc])$", "", n)
    return n


@dataclass
class Finding:
    severity: str          # error | warning | info | ok
    code: str
    symbol: str
    message: str
    detail: str = ""

    def render(self) -> str:
        icon = {"error": "🔴", "warning": "🟠", "info": "🟡", "ok": "✅"}[self.severity]
        base = f"{icon} [{self.code}] {self.symbol}: {self.message}"
        return f"{base}\n     {self.detail}" if self.detail else base


@dataclass
class RealityReport:
    findings: list[Finding] = field(default_factory=list)

    def render(self) -> str:
        by = {"error": 0, "warning": 0, "info": 0, "ok": 0}
        for f in self.findings:
            by[f.severity] += 1
        head = (f"Reality-check: {by['error']} error(es), {by['warning']} warning(s), "
                f"{by['info']} info, {by['ok']} ok\n")
        return head + "\n".join(f.render() for f in self.findings)


# ---------------------------------------------------------------- carga de fuentes

def load_broker_specs(csv_path: str | Path) -> dict[str, dict]:
    """{norm: {real_name, point, digits, spread, swap_long, swap_short}}"""
    out: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("digits", "") == "" or "NO_EXISTE" in str(r):
                continue
            out[_norm(r["name"])] = {
                "real_name": r["name"], "point": float(r["point"]),
                "digits": int(r["digits"]), "spread": int(r["spread"] or 0),
                "swap_long": float(r["swap_long"]), "swap_short": float(r["swap_short"]),
            }
    return out


def load_broker_sessions(csv_path: str | Path) -> dict[str, list[tuple[str, str, str]]]:
    """{real_name: [(day, from HH:MM, to HH:MM), ...]}"""
    out: dict[str, list[tuple[str, str, str]]] = {}
    with open(csv_path, encoding="utf-8", errors="replace") as f:
        for r in csv.DictReader(f, delimiter=";"):
            if r.get("day") in (None, "NO_EXISTE") or not r.get("session_from"):
                continue
            out.setdefault(r["symbol"], []).append(
                (r["day"], r["session_from"], r["session_to"]))
    return out


# ---------------------------------------------------------------- helpers

def _cfg_trading(cfg) -> dict:
    """{key: value} de las trading options del builder."""
    s = cfg.settings or {}
    tr = s.get("trading_options") or []
    return {p["key"]: p.get("value") for p in tr if isinstance(p, dict) and "key" in p}


def _cfg_slpt(cfg) -> dict:
    """SLPTOptions del builder (what_to_build.slpt_options)."""
    return (cfg.what_to_build or {}).get("slpt_options") or {}


def _cfg_raw_xml(cfg) -> str:
    return getattr(cfg, "_raw_xml", "") or ""


def _hhmm_to_min(s: str) -> int:
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _sessions_intervals(raw: list[tuple[str, str, str]]) -> dict[str, list[tuple[int, int]]]:
    """Convierte las sesiones crudas a {day: [(from_min, to_min)]} manejando cruce de
    medianoche (to == 00:00 y from > to → intervalo [from, 1440])."""
    iv: dict[str, list[tuple[int, int]]] = {}
    for day, tf, tt in raw:
        f, t = _hhmm_to_min(tf), _hhmm_to_min(tt)
        if t == 0 and f > 0:
            t = 1440
        iv.setdefault(day, []).append((f, t))
    return iv


def _in_sessions(iv: dict[str, list[tuple[int, int]]], day: str, a: int, b: int) -> bool:
    """¿[a,b) de minutos está cubierto por las sesiones de ese día?"""
    for f, t in sorted(iv.get(day, [])):
        if f <= a and b <= t:
            return True
    return False


# ---------------------------------------------------------------- checks

def _find_mc_spread_range(root: ET.Element) -> tuple[float, float] | None:
    """Rango RandomizeSpread activo en el XML de un Retest del project."""
    for mc in root.iter("MonteCarloRetest"):
        if mc.get("use") != "true":
            continue
        for meth in mc.iter("Method"):
            if meth.get("use") == "true" and meth.get("type") == "RandomizeSpread":
                lo = meth.find("./Params/Param[@key='Min']")
                hi = meth.find("./Params/Param[@key='Max']")
                if lo is not None and hi is not None and lo.text and hi.text:
                    return float(lo.text), float(hi.text)
    return None


def check_spread_vs_mc(rep: RealityReport, project_path: str, specs: dict, base: str):
    """MC-Retest con spread irreal frente al spread vivo del broker."""
    import zipfile
    try:
        z = zipfile.ZipFile(project_path)
    except Exception:
        return
    with z:
        for name in z.namelist():
            if not name.startswith("Retest-Task"):
                continue
            root = ET.fromstring(z.read(name))
            rng = _find_mc_spread_range(root)
            if not rng:
                continue
            lo, hi = rng
            # spread real: el del símbolo pedido, o el primero no-cero disponible
            real = (specs.get(base, {}).get("spread")
                    or next((v["spread"] for v in specs.values() if v["spread"] > 0), 0))
            label = specs.get(base, {}).get("real_name", base or "?")
            if not real:
                rep.findings.append(Finding(
                    "info", "spread_desconocido", label,
                    f"MC-Retest perturba spread {lo:g}–{hi:g} pero no hay spread real en el CSV "
                    f"(¿mercado cerrado al exportar?)",
                    "correr mt5-sync en horario de mercado y repetir"))
                continue
            if hi < real:
                factor = real / max(hi, 1e-9)
                rep.findings.append(Finding(
                    "error", "spread_mc_irreal", f"{label} (MC-Retest)",
                    f"MC perturba spread {lo:g}–{hi:g} pero el broker cobra {real} points ({factor:.0f}× más)",
                    f"subir RandomizeSpread Max a ≈{real * 1.15:.0f}; el test actual aprueba "
                    f"estrategias que mueren con costos reales"))
            else:
                rep.findings.append(Finding(
                    "ok", "spread_mc_ok", label,
                    f"MC-Retest spread {lo:g}–{hi:g} ≥ spread real {real} ✓"))


def check_min_pt_vs_spread(rep: RealityReport, cfg, specs: dict, sym_norm: str):
    """El PT mínimo (pips) vs spread real: margen neto por trade."""
    spec = specs.get(sym_norm)
    if not spec:
        return
    min_pt = _cfg_slpt(cfg).get("MinPTInPips")
    if min_pt in (None, ""):
        return
    min_pt = float(min_pt)
    spread = spec["spread"]
    if spread <= 0:
        rep.findings.append(Finding(
            "info", "spread_desconocido", sym_norm,
            "Spread real no disponible (mercado cerrado al exportar)"))
        return
    # en SQX "pips" para índices = points del símbolo
    neto = float(min_pt) - spread
    ratio = float(min_pt) / spread if spread else 0
    if ratio < 1.2:
        rep.findings.append(Finding(
            "error", "pt_bajo_spread", sym_norm,
            f"PT mínimo {min_pt:g} < 1.2× spread ({spread}) — margen neto {neto:g} pts",
            "subir MinPTInPips a ≈" f"{1.25 * spread:.0f} o el trade nace casi sin margen"))
    elif ratio < 1.5:
        rep.findings.append(Finding(
            "warning", "pt_ajustado_spread", sym_norm,
            f"PT mínimo {min_pt:g} = {ratio:.2f}× spread — margen neto fino ({neto:g} pts)"))
    else:
        rep.findings.append(Finding(
            "ok", "pt_ok_spread", sym_norm,
            f"PT mínimo {min_pt:g} = {ratio:.2f}× spread (margen neto {neto:g} pts)"))


def check_ventana_vs_sesion(rep: RealityReport, cfg, sess: dict, sym_real: str | None):
    """La ventana SignalTimeRange del builder dentro de las sesiones reales del símbolo."""
    if not sym_real or sym_real not in sess:
        return
    opts = _cfg_trading(cfg)
    lim, a, b = opts.get("LimitTimeRange"), opts.get("SignalTimeRangeFrom"), opts.get("SignalTimeRangeTo")
    if not lim or a is None or b is None:
        return
    a, b = int(a), int(b)
    # SQX guarda SignalTimeRange* en SEGUNDOS desde medianoche (28800 = 08:00)
    def to_min(v: int) -> int:
        return v // 60 if v >= 1440 else (v // 100) * 60 + (v % 100)
    af, bf = to_min(a), to_min(b)
    iv = _sessions_intervals(sess[sym_real])
    ok_days, bad_days = [], []
    for day in DAYS[1:6]:  # Mon..Fri
        if _in_sessions(iv, day, af, bf):
            ok_days.append(day)
        else:
            bad_days.append(day)
    fh, fm = divmod(af, 60); th, tm = divmod(bf, 60)
    ventana = f"{fh:02d}:{fm:02d}–{th:02d}:{tm:02d} UTC (servidor)"
    if bad_days:
        rep.findings.append(Finding(
            "error", "ventana_fuera_sesion", sym_real,
            f"Ventana del builder {ventana} NO está cubierta por la sesión real en {', '.join(bad_days)}",
            "el builder generaría señales en horas que el broker no cotiza"))
    else:
        rep.findings.append(Finding(
            "ok", "ventana_ok", sym_real,
            f"Ventana del builder {ventana} dentro de la sesión real (Mon–Fri) ✓"))


def check_time_stop_vs_sesion(rep: RealityReport, cfg, sess: dict, sym_real: str | None):
    """ExitAfterBars de N barras H1: ¿la ventana de entrada + N h cruza el cierre diario?"""
    if not sym_real or sym_real not in sess:
        return
    # obtener rango de barras del OrderType si existe
    bars = None
    xml_text = getattr(cfg, "_raw_xml", None)
    if xml_text:
        m = re.search(r'key="#ExitAfterBars\.ExitAfterBars#"[^>]*minValue="(\d+)" maxValue="(\d+)"',
                      xml_text)
        if m:
            bars = int(m.group(2))  # peor caso: máximo
    if not bars:
        return
    rep.findings.append(Finding(
        "info", "time_stop_info", sym_real,
        f"Time-stop de hasta {bars} barras H1: verificar que las últimas {bars}h de la "
        f"ventana no crucen el cierre del símbolo (gap del rollover)",
        f"sesión real: {sess[sym_real]}"))


def check_swap_direccion(rep: RealityReport, cfg, specs: dict, sym_norm: str,
                         direction: str = "short"):
    spec = specs.get(sym_norm)
    if not spec:
        return
    swap = spec["swap_short"] if direction == "short" else spec["swap_long"]
    label = "short" if direction == "short" else "long"
    if swap < 0:
        rep.findings.append(Finding(
            "warning", "swap_costo", sym_norm,
            f"Swap {label}: {swap:g} pts por noche — costo real en strategies que "
            f"mantienen posiciones overnight"))
    else:
        rep.findings.append(Finding(
            "ok", "swap_ok", sym_norm, f"Swap {label}: {swap:g} (sin costo)"))


def check_breakeven_con_costos(rep: RealityReport, cfg, specs: dict, sym_norm: str):
    """Win rate de breakeven real: RRR + spread relativo al PT."""
    spec = specs.get(sym_norm)
    if not spec or spec["spread"] <= 0:
        return
    slpt = _cfg_slpt(cfg)
    rrr_lo, rrr_hi = slpt.get("LimitSLPTRRRFrom"), slpt.get("LimitSLPTRRRTo")
    if rrr_lo in (None, "") or rrr_hi in (None, ""):
        return
    rrr_lo, rrr_hi = float(rrr_lo), float(rrr_hi)
    # RRR% 60 = PT = 0.6×SL → breakeven = 1/(1+0.6) = 62.5%
    spread = spec["spread"]
    worst = 1.0 / (1.0 + float(rrr_lo) / 100.0)
    best = 1.0 / (1.0 + float(rrr_hi) / 100.0)
    rep.findings.append(Finding(
        "info", "breakeven_costos", sym_norm,
        f"RRR {rrr_lo:g}–{rrr_hi:g}% → breakeven teórico {best*100:.1f}–{worst*100:.1f}% · "
        f"el spread ({spread} pts) agrega ~{spread / max(float(rrr_hi), 1e-9):.0%} de "
        f"breakeven extra en el extremo de PT corto",
        "los filtros de win rate del builder deben superar el breakeven CON costos, "
        "no el teórico"))


# ---------------------------------------------------------------- entry point

def reality_check(cfx_path: str | Path, project_path: str | Path | None = None,
                  specs_csv: str | Path | None = None,
                  sessions_csv: str | Path | None = None,
                  symbols: str = "USTECm", direction: str = "short") -> RealityReport:
    """Cruza el .cfx (y opcionalmente el project) con las specs/sesiones reales del broker."""
    rep = RealityReport()
    specs = load_broker_specs(specs_csv) if specs_csv else {}
    sess = load_broker_sessions(sessions_csv) if sessions_csv else {}
    if not specs:
        rep.findings.append(Finding(
            "warning", "sin_specs", "-",
            "Sin CSV de specs del broker: los checks de costos quedan desactivados",
            "correr mt5-sync primero"))
    cfg = parse_cfx(cfx_path)
    requested = [s.strip() for s in symbols.split(",") if s.strip()]

    for sym in requested:
        n = _norm(sym)
        real_name = specs.get(n, {}).get("real_name", sym)
        check_min_pt_vs_spread(rep, cfg, specs, n)
        check_ventana_vs_sesion(rep, cfg, sess, real_name)
        check_swap_direccion(rep, cfg, specs, n, direction)
        check_breakeven_con_costos(rep, cfg, specs, n)
        check_time_stop_vs_sesion(rep, cfg, sess, real_name)

    if project_path:
        check_spread_vs_mc(rep, str(project_path), specs,
                           _norm(requested[0]) if requested else "")
    return rep
