"""Automatización MT5 → SQX: exporta especificaciones reales del broker y genera
el Instruments.xml corregido para StrategyQuant.

Flujo completo (un comando):
  1. Detecta el data folder de MT5 (o usa el dado)
  2. Escribe un script MQL5 que consulta SymbolInfo* del broker en vivo
  3. Lo compila headless con MetaEditor64.exe /compile
  4. Relanza el terminal con /config:[StartUp] Script=... (mata la instancia previa
     si --restart-terminal; MT5 solo permite una instancia por data folder)
  5. Espera el CSV en MQL5/Files y lo parsea
  6. Compara contra el Instruments.xml actual de SQX y genera el corregido

Solo Windows (se invoca via powershell.exe; desde WSL funciona igual).
"""
from __future__ import annotations

import csv
import html
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_SYMBOLS = "USTECm,US30m,US500m,USOILm,UKOILm,XAGUSDm,XAUUSDm,XNGUSDm"

MQ5_SCRIPT = r'''//+------------------------------------------------------------------+
//| ExportSpecsAuto.mq5 - exporta especificaciones de simbolos (SQX) |
//| Generado por SQXTools — no editar a mano                         |
//+------------------------------------------------------------------+
void OnStart()
{
   string syms[] = {__SYMBOLS__};
   int h = FileOpen("__OUT_CSV__", FILE_WRITE|FILE_CSV|FILE_ANSI, ';');
   if(h == INVALID_HANDLE) { Print("SQXTOOLS: no se pudo abrir __OUT_CSV__"); return; }
   FileWrite(h, "name","description","path","digits","point","spread","stops_level",
             "tick_value","tick_size","contract","swap_long","swap_short");
   for(int i=0; i<ArraySize(syms); i++)
   {
      string s = syms[i];
      if(!SymbolSelect(s, true)) { FileWrite(h, s, "NO_EXISTE"); continue; }
      FileWrite(h, s,
         SymbolInfoString(s, SYMBOL_DESCRIPTION),
         SymbolInfoString(s, SYMBOL_PATH),
         IntegerToString(SymbolInfoInteger(s, SYMBOL_DIGITS)),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_POINT), 10),
         IntegerToString(SymbolInfoInteger(s, SYMBOL_SPREAD)),
         IntegerToString(SymbolInfoInteger(s, SYMBOL_TRADE_STOPS_LEVEL)),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_TRADE_TICK_VALUE), 10),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_TRADE_TICK_SIZE), 10),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_TRADE_CONTRACT_SIZE), 4),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_SWAP_LONG), 4),
         DoubleToString(SymbolInfoDouble(s, SYMBOL_SWAP_SHORT), 4));
   }
   FileClose(h);
   Print("SQXTOOLS: specs listas en __OUT_CSV__");
}
'''

STARTUP_INI = "[StartUp]\nScript=ExportSpecsAuto\n"


@dataclass
class Mt5Spec:
    name: str
    description: str = ""
    path: str = ""
    digits: int = 0
    point: float = 0.0
    spread: int = 0
    stops_level: int = 0
    tick_value: float = 0.0
    tick_size: float = 0.0
    contract: float = 0.0
    swap_long: float = 0.0
    swap_short: float = 0.0
    exists: bool = True


@dataclass
class SyncReport:
    specs: list[Mt5Spec] = field(default_factory=list)
    diffs: list[dict] = field(default_factory=list)
    xml_out: str = ""
    log: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- powershell helpers

def _ps(command: str, timeout: int = 120) -> str:
    out = subprocess.run(["powershell.exe", "-NoProfile", "-Command", command],
                         capture_output=True, text=True, timeout=timeout)
    if out.returncode != 0 and not out.stdout:
        raise RuntimeError(f"powershell falló: {out.stderr[:400]}")
    return out.stdout.strip()


def _wsl(win_path: str) -> Path:
    """C:\\x\\y → /mnt/c/x/y"""
    m = re.match(r"([A-Za-z]):[\\/](.*)", win_path.replace("/", "\\"))
    if not m:
        raise ValueError(f"ruta Windows no reconocida: {win_path}")
    drive, rest = m.groups()
    return Path("/mnt") / drive.lower() / rest.replace("\\", "/")


# ---------------------------------------------------------------- detección

def find_data_folder(explicit: str = "") -> str:
    """Devuelve la ruta Windows del data folder activo de MT5."""
    if explicit:
        if _wsl(explicit).exists():
            return explicit.rstrip("\\/")
        raise FileNotFoundError(f"El data folder no existe: {explicit}")
    # detectar usuario Windows desde WSL, o usar la ruta tal cual en Windows nativo
    wsl_users = Path("/mnt/c/Users")
    if wsl_users.exists():
        user = next((u.name for u in wsl_users.iterdir()
                     if (u / "AppData/Roaming/MetaQuotes/Terminal").exists()
                     and u.name not in ("Public", "Default", "Default User", "All Users")), None)
        if not user:
            raise FileNotFoundError("Ningún usuario de Windows tiene MetaQuotes/Terminal")
        base = rf"C:\Users\{user}\AppData\Roaming\MetaQuotes\Terminal"
    else:
        base = r"C:\Users\%USERNAME%\AppData\Roaming\MetaQuotes\Terminal"
    candidates = []
    wsl_base = _wsl(base)
    if not wsl_base.exists():
        raise FileNotFoundError("No hay MetaQuotes/Terminal en el perfil de usuario")
    for d in wsl_base.iterdir():
        if not d.is_dir() or len(d.name) != 32:
            continue
        log_dir = d / "logs"
        if not log_dir.exists():
            continue
        newest = max((f.stat().st_mtime for f in log_dir.glob("*.log")), default=0)
        candidates.append((newest, d.name))
    if not candidates:
        raise FileNotFoundError("No se encontró ningún data folder con logs de MT5")
    candidates.sort(reverse=True)
    return f"{base}\\{candidates[0][1]}"


def find_broker_postfix(specs: list[Mt5Spec], requested: list[str]) -> tuple[list[str], str]:
    """Resuelve el sufijo real del broker probando variantes (_exness, m, c, sin sufijo).
    Devuelve (nombres_resueltos, sufijo_detectado)."""
    if not specs:
        return requested, ""
    available = {s.name for s in specs}
    all_syms = set(available)
    resolved, suffix = [], ""
    for want in requested:
        base = re.sub(r"(_exness|[mc])$", "", want)
        for cand in (want, f"{base}_exness", f"{base}m", f"{base}c", base):
            if cand in all_syms:
                resolved.append(cand)
                if cand.endswith("_exness"):
                    suffix = "_exness"
                elif cand != base and not suffix:
                    suffix = cand[len(base):]
                break
        else:
            resolved.append(want)  # se reportará como NO_EXISTE
    return resolved, suffix


# ---------------------------------------------------------------- pipeline

def sync(mt5_path: str, data_folder: str = "", symbols: str = DEFAULT_SYMBOLS,
         instruments_xml: str = "", out_xml: str = "", restart_terminal: bool = False,
         skip_run: bool = False) -> SyncReport:
    """Ejecuta el flujo completo y devuelve el reporte con el XML corregido."""
    rep = SyncReport()
    log = rep.log.append
    mt5_path = mt5_path.rstrip("\\/")
    editor = f"{mt5_path}\\MetaEditor64.exe"
    terminal = f"{mt5_path}\\terminal64.exe"
    if not _wsl(editor).exists():
        raise FileNotFoundError(f"MetaEditor64.exe no encontrado en {mt5_path}")
    df = find_data_folder(data_folder)
    dfw = _wsl(df)
    log(f"data folder: {df}")

    requested = [s.strip() for s in symbols.split(",") if s.strip()]

    # 1. escribir script MQL5
    scripts = dfw / "MQL5" / "Scripts"
    scripts.mkdir(parents=True, exist_ok=True)
    sym_list = ", ".join(f'"{s}"' for s in requested)
    (scripts / "ExportSpecsAuto.mq5").write_text(
        MQ5_SCRIPT.replace("__SYMBOLS__", sym_list).replace("__OUT_CSV__", "sqx_specs.csv"),
        encoding="utf-8")
    log("script MQL5 escrito")

    # 2. compilar headless
    r = _ps(f'''
Set-Location "{df}\\MQL5\\Scripts"
$arg = "/compile:{df}\\MQL5\\Scripts\\ExportSpecsAuto.mq5 /log:{df}\\MQL5\\Scripts\\sqx_compile.log"
$p = Start-Process -FilePath "{editor}" -ArgumentList $arg -Wait -PassThru
"exit=" + $p.ExitCode
''')
    clog = (scripts / "sqx_compile.log")
    txt = clog.read_bytes().decode("utf-16-le", errors="ignore") if clog.exists() else r
    m = re.search(r"Result:\s*(\d+) errors?[^,]*,\s*(\d+) warnings?", txt)
    if not m or m.group(1) != "0":
        raise RuntimeError(f"Compilación MQL5 falló:\n{txt[-800:]}")
    log("compilación OK (0 errores)")

    # 3. ejecutar
    csv_wsl = dfw / "MQL5" / "Files" / "sqx_specs.csv"
    if skip_run:
        if not csv_wsl.exists():
            raise FileNotFoundError("skip_run pero no existe sqx_specs.csv previo")
        log("usando CSV existente (skip_run)")
    else:
        if csv_wsl.exists():
            csv_wsl.unlink()
        running = _ps('(Get-Process terminal64 -ErrorAction SilentlyContinue) -ne $null').lower()
        cfg_path = f"{df}\\config\\sqx_startup.ini"
        (dfw / "config" / "sqx_startup.ini").write_text(STARTUP_INI, encoding="utf-8")
        if running == "true":
            if not restart_terminal:
                raise RuntimeError(
                    "MT5 está corriendo. Sin --restart-terminal no puedo relanzarlo con el "
                    "script de arranque. Cerrá MT5 y volvé a correr, o usá --restart-terminal.")
            _ps('Stop-Process -Name terminal64 -Force; Start-Sleep -Seconds 3')
            log("terminal previo cerrado")
        _ps(f'Start-Process -FilePath "{terminal}" -ArgumentList "/config:{cfg_path}"')
        log("terminal relanzado con script de arranque; esperando CSV...")
        deadline = time.time() + 90
        while time.time() < deadline and not csv_wsl.exists():
            time.sleep(2)
        if not csv_wsl.exists():
            raise TimeoutError("El CSV no apareció en 90s (¿el script corrió? revisá la pestaña Expertos)")
        time.sleep(2)
        log("CSV recibido")

    # 4. parsear
    with open(csv_wsl, encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    for r_ in rows:
        if r_.get("description") == "NO_EXISTE" or r_.get("digits", "") == "" and "NO_EXISTE" in str(r_):
            rep.specs.append(Mt5Spec(name=r_["name"], exists=False))
            continue
        rep.specs.append(Mt5Spec(
            name=r_["name"], description=r_.get("description", ""), path=r_.get("path", ""),
            digits=int(r_["digits"]), point=float(r_["point"]), spread=int(r_["spread"] or 0),
            stops_level=int(r_["stops_level"] or 0), tick_value=float(r_["tick_value"]),
            tick_size=float(r_["tick_size"]), contract=float(r_["contract"]),
            swap_long=float(r_["swap_long"]), swap_short=float(r_["swap_short"])))
    missing = [s.name for s in rep.specs if not s.exists]
    if missing:
        log(f"⚠️ símbolos inexistentes en el broker: {', '.join(missing)}")
    log(f"{sum(1 for s in rep.specs if s.exists)}/{len(rep.specs)} símbolos exportados")

    # 5. comparar + generar XML
    prev = parse_prev_xml(instruments_xml) if instruments_xml else {}
    rep.xml_out = generate_instruments_xml(rep.specs, prev=prev)
    if instruments_xml:
        rep.diffs = compare_with_xml(rep.specs, instruments_xml)
        log(f"comparado con {instruments_xml}: {len(rep.diffs)} diferencia(s)")
    if out_xml:
        Path(out_xml).parent.mkdir(parents=True, exist_ok=True)
        Path(out_xml).write_text(rep.xml_out, encoding="utf-8")
        log(f"XML corregido → {out_xml}")
    return rep


# ---------------------------------------------------------------- XML

def generate_instruments_xml(specs: list[Mt5Spec], prev: dict[str, dict] | None = None,
                             broker_id: int = 12, broker_name: str = "[Exness]",
                             postfix: str = "_exness") -> str:
    """Genera el Instruments.xml con las specs reales del servidor.
    `prev` = {base_name: {spread, triple, ...}} del XML anterior para rellenar
    lo que el servidor no pudo dar en vivo (spread en mercado cerrado)."""
    prev = prev or {}
    comm = '<Method type="None" use="true"><Params/></Method>'
    out = ["<Instruments>"]
    for s in specs:
        if not s.exists:
            continue
        def _norm(n: str) -> str:
            return re.sub(r"(_exness|[mc])$", "", n)

        base = _norm(s.name)
        p = prev.get(base, prev.get(s.name, {}))
        triple = p.get("triple", "WEDNESDAY" if base.startswith("X") or base.startswith(("USOIL", "UKOIL")) else "FRIDAY")
        spread = s.spread if s.spread > 0 else p.get("spread", 0)
        # pointValue real = tick_value/tick_size; si el servidor no cotiza (tv=0) heredar del XML previo
        point_value = (s.tick_value / s.tick_size) if (s.tick_size and s.tick_value) else p.get("pointValue", 0.0)
        swap = (f'<Swap use="true" type="points" long="{s.swap_long:g}" short="{s.swap_short:g}" '
                f'tripleSwapOn="{triple}" rolloutHour="23:00"/>')
        attrs = (f'instrument="{s.name}{postfix}" description="{html.escape(s.description, quote=True)}" '
                 f'tickSize="{s.point:g}" tickStep="{s.point:g}" minDistance="0.0" tickValueInMoney="0.0" '
                 f'dateFrom="0" dateTo="0" rows="0" totalDays="0" defaultSpread="{spread:g}" '
                 f'defaultSlippage="0.0" decimals="{s.digits}" commissions="{html.escape(comm, quote=True)}" '
                 f'pointValue="{point_value:g}" dataType="3" '
                 f'recognizedFromOrders="false" exchange="" country="" sector="" '
                 f'swap="{html.escape(swap, quote=True)}" orderSizeMultiplier="1.0" orderSizeStep="0.01" '
                 f'broker="{broker_id}"')
        out.append(f"  <InstrumentInfo {attrs} />")
    out.append(f'  <Broker id="{broker_id}" name="{broker_name}" description="{broker_name.strip("[]")}" '
               f'timezone="Etc/UCT" postfix="{postfix}" mtUse="true" spUse="true" />')
    out.append("</Instruments>")
    return "\n".join(out) + "\n"


def compare_with_xml(specs: list[Mt5Spec], instruments_xml: str | Path) -> list[dict]:
    """Diferencias entre el Instruments.xml actual de SQX y las specs reales."""
    raw = Path(instruments_xml).read_text(encoding="utf-8", errors="replace")
    diffs: list[dict] = []
    for m in re.finditer(r"<InstrumentInfo\s+(.*?)/>\s*(?:\n|<Broker|$)", raw, re.S):
        attrs = m.group(1)

        def attr(name: str, a=attrs) -> str:
            am = re.search(rf'{name}="([^"]*)"', a)
            return am.group(1) if am else ""

        inst = attr("instrument")

        def _norm(n: str) -> str:
            prev_n = None
            while prev_n != n:
                prev_n = n
                n = re.sub(r"(_exness|[mc])$", "", n)
            return n

        base = _norm(inst)
        spec = next((s for s in specs if _norm(s.name) == base), None)
        if spec is None or not spec.exists:
            diffs.append({"symbol": inst, "field": "existencia",
                          "xml": "presente", "broker": "NO_ENCONTRADO"})
            continue
        checks = [
            ("tickSize", float(attr("tickSize") or 0), spec.point, lambda a, b: abs(a - b) > 1e-9),
            ("decimals", int(attr("decimals") or 0), spec.digits, lambda a, b: a != b),
            ("swap_long", float(attr("long", ) or 0), spec.swap_long, lambda a, b: abs(a - b) > 0.51),
        ]
        swap_m = re.search(r'swap="([^"]*)"', attrs)
        swap_xml = html.unescape(swap_m.group(1)) if swap_m else ""
        sl = re.search(r'long="(-?[\d.]+)"', swap_xml)
        ss = re.search(r'short="(-?[\d.]+)"', swap_xml)
        checks = [
            ("tickSize", float(attr("tickSize") or 0), spec.point),
            ("decimals", int(attr("decimals") or 0), spec.digits),
            ("swap_long", float(sl.group(1)) if sl else 0.0, spec.swap_long),
            ("swap_short", float(ss.group(1)) if ss else 0.0, spec.swap_short),
        ]
        for field_, xml_v, broker_v in checks:
            if abs(xml_v - broker_v) > (0.51 if "swap" in field_ else 1e-9):
                diffs.append({"symbol": inst, "field": field_,
                              "xml": xml_v, "broker": broker_v})
        # pointValue vs tick_value/tick_size
        if spec.tick_value and spec.tick_size:  # sin cotización viva el servidor da 0 → no comparar
            pv = float(attr("pointValue") or 0)
            real_pv = spec.tick_value / spec.tick_size
            if abs(pv - real_pv) / max(real_pv, 1e-9) > 0.01:
                diffs.append({"symbol": inst, "field": "pointValue", "xml": pv, "broker": round(real_pv, 4)})
    return diffs


def parse_prev_xml(instruments_xml: str | Path) -> dict[str, dict]:
    """Extrae {base: {spread, triple}} del XML anterior (para rellenar huecos)."""
    raw = Path(instruments_xml).read_text(encoding="utf-8", errors="replace")
    out: dict[str, dict] = {}
    for m in re.finditer(r"<InstrumentInfo\s+(.*?)/>\s*(?:\n|<Broker|$)", raw, re.S):
        attrs = m.group(1)
        am = re.search(r'instrument="([^"]*)"', attrs)
        if not am:
            continue
        base = am.group(1).replace("_exness", "")
        sm = re.search(r'[dD]efaultSpread="([\d.]+)"', attrs)
        tm = re.search(r'tripleSwapOn="([A-Z]+)"', attrs)
        pvm = re.search(r'pointValue="([\d.]+)"', attrs)
        out[base] = {"spread": float(sm.group(1)) if sm else 0.0,
                     "triple": tm.group(1) if tm else "WEDNESDAY",
                     "pointValue": float(pvm.group(1)) if pvm else 0.0}
    return out
