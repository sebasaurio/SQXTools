"""Genera estrategias .sqx LONG para NAS100 H1 (y conserva la versión short).

Toma `Strategy 4.15.49.sqx` como plantilla y reemplaza la regla de señales y la
regla de entrada correspondiente a la dirección pedida. El resto de la estructura
se conserva intacto, porque es la parte que SQX necesita para abrir el archivo.

Los edges de "quiebre de nivel" se prueban en las DOS direcciones (short y long)
con el esquema de salida por trailing. Los edges de momentum (RSI>70, CCI>150)
usan SL 2 ATR / PT 2 ATR, que es el esquema con el que se midió su edge (+0.321 y
+0.334 R/trade en `signal-screen`).
"""

from __future__ import annotations

import os
import re
import zipfile

TEMPLATE = "/home/sebas/.hermes/cache/documents/doc_212d226e4ca7_Strategy 4.15.49.sqx"
OUT = "/home/sebas/SQXTools/output/edges/estrategias"
os.makedirs(OUT, exist_ok=True)

LONG_VAR = "33333333-1111-1111-3333-333333333333"    # LongEntrySignal
SHORT_VAR = "33333333-2222-1111-3333-333333333333"   # ShortEntrySignal


# ── Bloques de condición (Item) ───────────────────────────────────────────────

def _comparison(op: str, left: str, right: str, gid: str) -> str:
    name = {"IsGreater": "(&gt;) Is greater", "IsLower": "(&lt;) Is lower",
            "CrossesAbove": "Crosses above", "CrossesBelow": "Crosses below"}[op]
    display = {"IsGreater": "#Left# &gt; #Right#", "IsLower": "#Left# &lt; #Right#",
               "CrossesAbove": "#Left# crosses above #Right#",
               "CrossesBelow": "#Left# crosses below #Right#"}[op]
    return (f'<Item customSnippet="false" key="{op}" name="{name}" display="{display}" '
            'returnType="boolean" mI="Comparisons" categoryType="operators" '
            f'generated="random" randomId="RandomConditionShort" retries="0" gid="{gid}">'
            f'<Block key="#Left#">{left}</Block><Block key="#Right#">{right}</Block></Item>')


def _price_item(key: str, name: str, display: str, gid: str, shift: str = "0") -> str:
    return (f'<Item customSnippet="false" key="{key}" name="{name}" display="{display}" '
            'returnType="price" mI="Other" categoryType="indicator" generated="random" '
            f'randomId="RandomConditionShort" gid="{gid}">'
            '<Param key="#Chart#" controlType="dataVar" type="data">0</Param>'
            f'<Param key="#Shift#" controlType="jspinnerVar" type="int" gid="{gid}">{shift}</Param>'
            '</Item>')


def _close(gid: str) -> str:
    return _price_item("Close", "(CLS) Close", "Close(@Chart@)[#Shift#]", gid)


def _close_d(gid: str) -> str:
    return _price_item("CloseD", "(CLSD) Close of day", "CloseD(@Chart@)[#Shift#]", gid, "1")


def _high_w(gid: str) -> str:
    return _price_item("HighW", "(HIGHW) High of week", "HighW(@Chart@)[#Shift#]", gid, "1")


def _session_price(key: str, name: str, display: str, gid: str) -> str:
    return (f'<Item customSnippet="false" key="{key}" name="{name}" display="{display}" '
            'returnType="price" mI="Other" categoryType="indicator" generated="random" '
            f'randomId="RandomConditionShort" gid="{gid}">'
            '<Param key="#Chart#" controlType="dataVar" type="data">0</Param>'
            f'<Param key="#StartHours#" controlType="jspinnerVar" type="int" gid="{gid}">20</Param>'
            f'<Param key="#StartMinutes#" controlType="jspinnerVar" type="int" gid="{gid}">0</Param>'
            f'<Param key="#EndHours#" controlType="jspinnerVar" type="int" gid="{gid}">12</Param>'
            f'<Param key="#EndMinutes#" controlType="jspinnerVar" type="int" gid="{gid}">0</Param>'
            f'<Param key="#Shift#" controlType="jspinnerVar" type="int" gid="{gid}">1</Param>'
            '</Item>')


def _session_low(gid: str) -> str:
    return _session_price("SessionLow", "(SL) Session low",
                          "SessionLow(@Chart@, #StartHours#:#StartMinutes#, #EndHours#:#EndMinutes#)[#Shift#]", gid)


def _session_high(gid: str) -> str:
    return _session_price("SessionHigh", "(SH) Session high",
                          "SessionHigh(@Chart@, #StartHours#:#StartMinutes#, #EndHours#:#EndMinutes#)[#Shift#]", gid)


def _oscillator_item(key: str, name: str, display: str, gid: str, period_param: str, extra: str = "") -> str:
    return (f'<Item customSnippet="false" key="{key}" name="{name}" display="{display}" '
            'returnType="number" mI="Other" categoryType="indicator" isOscillator="true" '
            f'middleValue="0" generated="random" randomId="RandomConditionShort" gid="{gid}">'
            '<Param key="#Chart#" controlType="dataVar" type="data">0</Param>'
            f'<Param key="#ComputedFrom#" controlType="combo" type="int">0</Param>{extra}'
            f'<Param key="{period_param}" controlType="jspinnerVar" type="int" gid="{gid}">14</Param>'
            f'<Param key="#Shift#" controlType="jspinnerVar" type="int" gid="{gid}">0</Param>'
            '</Item>')


def _rsi(gid: str) -> str:
    return _oscillator_item("RSI", "(RSI) Relative Strength Index",
                            "RSI(@Chart@#Period#)[#Shift#]", gid, "#Period#")


def _cci(gid: str) -> str:
    return _oscillator_item("CCI", "(CCI) Commodity Channel Index",
                            "CCI(@Chart@#Period#)[#Shift#]", gid, "#Period#")


def _number(value: str, gid: str) -> str:
    return (f'<Item customSnippet="false" key="Number" name="(NUM) Number" display="#Number#" '
            'returnType="number" mI="Other" categoryType="other" notFirstValue="true" '
            f'generated="random" randomId="RandomConditionShort" gid="{gid}">'
            f'<Param key="#Number#" controlType="jspinner" type="double" gid="{gid}">{value}</Param>'
            '</Item>')


# ── Acciones de entrada ───────────────────────────────────────────────────────

def _entry_action(gid: str, scheme: str) -> str:
    """EnterAtMarket con el esquema de salida pedido: 'trailing' o 'slpt'."""
    if scheme == "slpt":
        pt = ('<Param key="#ProfitTarget.ProfitTarget#" controlType="SLPT" type="double" '
              'exitMethod="true" exitMethodType="PT"><Formula key="SQ.Formulas.SLPT.ATRBasedValue">'
              '<Param key="#Value#" controlType="jspinnerVar" type="double">2.0</Param>'
              '<Param key="#AtrPeriod#" controlType="jspinnerVar" type="int">14</Param>'
              '</Formula></Param>')
        trailing = (f'<Param key="#TrailingStop.TrailingStop#" controlType="RangeLevel" type="double" '
                    f'exitMethod="true" gid="{gid}" exitMethodType="SL">'
                    '<Formula key="SQ.Formulas.RangeLevel.None" /></Param>')
    else:  # trailing
        pt = ('<Param key="#ProfitTarget.ProfitTarget#" controlType="SLPT" type="double" '
              'exitMethod="true" exitMethodType="PT"><Formula key="SQ.Formulas.SLPT.None" /></Param>')
        trailing = (f'<Param key="#TrailingStop.TrailingStop#" controlType="RangeLevel" type="double" '
                    f'exitMethod="true" gid="{gid}" exitMethodType="SL">'
                    '<Formula key="SQ.Formulas.RangeLevel.ATRBasedValue">'
                    '<Param key="#Value#" controlType="jspinnerVar" type="double">1.5</Param>'
                    '<Param key="#AtrPeriod#" controlType="jspinnerVar" type="int">14</Param>'
                    '</Formula></Param>')
    return (
        '<Item customSnippet="false" key="EnterAtMarket" name="(MKT) Enter at market" '
        'display="EnterAtMarket" returnType="order" mI="Open" categoryType="other" '
        f'generated="random" randomId="RandomActionShort" retries="0" gid="{gid}">'
        f'<Param key="#Symbol#" controlType="symbolVar" type="string" gid="{gid}">Current</Param>'
        f'<Param key="#Size#" controlType="Size" type="double" isFormula="true" gid="{gid}">'
        '<Formula key="SQ.Formulas.Size.UseGlobalMM" /></Param>'
        f'<Param key="#Comment#" controlType="editbox" type="string" gid="{gid}"></Param>'
        f'<Param key="#AllowDuplicateTrades#" controlType="booleanVar" type="boolean" gid="{gid}">false</Param>'
        '<Param key="#ExitAfterBars.ExitAfterBars#" controlType="jspinnerVar" type="int" '
        f'exitMethod="true" gid="{gid}">24</Param>'
        '<Param key="#MoveSL2BE.MoveSL2BE#" controlType="RangeLevel" type="double" '
        f'exitMethod="true" isFormula="true" gid="{gid}" exitMethodType="SL">'
        '<Formula key="SQ.Formulas.RangeLevel.None" /></Param>'
        '<Param key="#MoveSL2BE.SL2BEAddPips#" controlType="Range" type="double" '
        f'exitMethod="true" isFormula="true" gid="{gid}" exitMethodType="SL" '
        'dependentOn="MoveSL2BE.MoveSL2BE"><Formula key="SQ.Formulas.Range.None" /></Param>'
        f'{pt}'
        '<Param key="#StopLoss.StopLoss#" controlType="SLPT" type="double" exitMethod="true" '
        f'exitMethodType="SL" gid="{gid}"><Formula key="SQ.Formulas.SLPT.ATRBasedValue">'
        '<Param key="#Value#" controlType="jspinnerVar" type="double">2.0</Param>'
        '<Param key="#AtrPeriod#" controlType="jspinnerVar" type="int">14</Param>'
        '</Formula></Param>'
        f'{trailing}'
        '<Param key="#TrailingStop.TrailingActivation#" controlType="Range" type="double" '
        f'exitMethod="true" isFormula="true" gid="{gid}" exitMethodType="SL" '
        'dependentOn="TrailingStop.TrailingStop"><Formula key="SQ.Formulas.Range.None" /></Param>'
        '</Item>')


# ── Definición de edges ───────────────────────────────────────────────────────

SHORT_EDGES = [
    {"slug": "01-overnight-low-cruce", "titulo": "Overnight low — cruce debajo",
     "cond": lambda g: _comparison("CrossesBelow", _close(g), _session_low(g), g),
     "ev": "exceso +0.057 (único que pasa los 5 filtros). n=675, 101/año.",
     "esquema": "trailing"},
    {"slug": "02-prev-day-close-cierre", "titulo": "Cierre día previo — cierra debajo",
     "cond": lambda g: _comparison("IsLower", _close(g), _close_d(g), g),
     "ev": "exceso +0.018, positivo en ambas mitades. n=1218, 182/año. La más sólida.",
     "esquema": "trailing"},
    {"slug": "03-prev-week-high-cruce", "titulo": "Máx semana previa — cruce debajo",
     "cond": lambda g: _comparison("CrossesBelow", _close(g), _high_w(g), g),
     "ev": "exceso +0.128 (el más alto) pero OOS −0.121. n=198, 30/año.",
     "esquema": "trailing"},
    {"slug": "04-overnight-high-retest", "titulo": "Máx overnight — cruce debajo",
     "cond": lambda g: _comparison("CrossesBelow", _close(g), _session_high(g), g),
     "ev": "exceso +0.050. n=825, 123/año.", "esquema": "trailing"},
    {"slug": "05-overnight-high-cierre", "titulo": "Máx overnight — cierra debajo",
     "cond": lambda g: _comparison("IsLower", _close(g), _session_high(g), g),
     "ev": "exceso +0.026. n=1560, 233/año.", "esquema": "trailing"},
]

LONG_EDGES = [
    {"slug": "long-01-overnight-low-cruce", "titulo": "Overnight low — cruce arriba (long)",
     "cond": lambda g: _comparison("CrossesAbove", _close(g), _session_low(g), g),
     "ev": "espejo del short. Long: el drift favorece los quiebres arriba.", "esquema": "trailing"},
    {"slug": "long-02-prev-day-close-arriba", "titulo": "Cierre día previo — cierra arriba (long)",
     "cond": lambda g: _comparison("IsGreater", _close(g), _close_d(g), g),
     "ev": "espejo del short. Long: cerrar por encima del cierre previo = momentum alcista.",
     "esquema": "trailing"},
    {"slug": "long-03-prev-week-high-cruce", "titulo": "Máx semana previa — cruce arriba (long)",
     "cond": lambda g: _comparison("CrossesAbove", _close(g), _high_w(g), g),
     "ev": "espejo del short. Ruptura del máximo semanal = continuación alcista.", "esquema": "trailing"},
    {"slug": "long-04-overnight-high-cruce", "titulo": "Máx overnight — cruce arriba (long)",
     "cond": lambda g: _comparison("CrossesAbove", _close(g), _session_high(g), g),
     "ev": "espejo del short. Ruptura del máximo overnight.", "esquema": "trailing"},
    {"slug": "long-05-overnight-high-arriba", "titulo": "Máx overnight — cierra arriba (long)",
     "cond": lambda g: _comparison("IsGreater", _close(g), _session_high(g), g),
     "ev": "espejo del short. Cerrar por encima del máximo overnight.", "esquema": "trailing"},
    {"slug": "long-rsi70", "titulo": "RSI > 70 (momentum long)",
     "cond": lambda g: _comparison("IsGreater", _rsi(g), _number("70", g), g),
     "ev": "+0.321 R/trade, win 58%, medido con SL2/PT2 (signal-screen).", "esquema": "slpt"},
    {"slug": "long-cci150", "titulo": "CCI > 150 (momentum long)",
     "cond": lambda g: _comparison("IsGreater", _cci(g), _number("150", g), g),
     "ev": "+0.334 R/trade, medido con SL2/PT2 (signal-screen).", "esquema": "slpt"},
]


# ── Construcción ──────────────────────────────────────────────────────────────

def _set_signals_rule(xml: str, cond: str, variable: str) -> str:
    m = re.search(r'(<Rule name="Trading signals"[^>]*>)(.*?)(</Rule>)', xml, re.S)
    if not m:
        raise ValueError("No se encontró la regla 'Trading signals'")
    body = f"<signals>\n  <signal variable=\"{variable}\">\n    {cond}\n  </signal>\n</signals>"
    return xml[:m.start(1)] + m.group(1) + body + xml[m.end(2):]


def _set_rule_then(xml: str, rule_name: str, action: str | None) -> str:
    """Setea el <Then> de la regla nombrada: acción, o <Then/> si action es None."""
    rm = re.search(r'<Rule[^>]*name="' + re.escape(rule_name) + r'".*?</Rule>', xml, re.S)
    if not rm:
        raise ValueError(f"regla no encontrada: {rule_name}")
    rule = rm.group(0)
    tm = re.search(r'<Then[^>]*>(.*?)</Then>', rule, re.S) or re.search(r'<Then[^>]*/>', rule, re.S)
    if not tm:
        raise ValueError(f"Then no encontrado en {rule_name}")
    replacement = "<Then />" if action is None else f"<Then>\n{action}\n</Then>"
    rule2 = rule[:tm.start()] + replacement + rule[tm.end():]
    return xml[:rm.start()] + rule2 + xml[rm.end():]


def build(e: dict, direction: str) -> str:
    z = zipfile.ZipFile(TEMPLATE)
    xml = z.read("strategy_Portfolio.xml").decode("utf-8", "replace")
    cond = e["cond"]("964789021")
    action = _entry_action("786920021", e.get("esquema", "trailing"))
    if direction == "long":
        xml = _set_signals_rule(xml, cond, LONG_VAR)
        xml = _set_rule_then(xml, "Long entry", action)
        xml = _set_rule_then(xml, "Short entry", None)
    else:
        xml = _set_signals_rule(xml, cond, SHORT_VAR)
        xml = _set_rule_then(xml, "Short entry", action)
        xml = _set_rule_then(xml, "Long entry", None)
    xml = xml.replace('<Strategy name=""', f'<Strategy name="{e["slug"]}"', 1)
    return xml


def write_sqx(xml: str, path: str) -> None:
    z = zipfile.ZipFile(TEMPLATE)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        for name in z.namelist():
            if name == "strategy_Portfolio.xml":
                out.writestr(name, xml)
            else:
                out.writestr(name, z.read(name))


def main():
    todos = [("long", e) for e in LONG_EDGES] + [("short", e) for e in SHORT_EDGES]
    for direction, e in todos:
        xml = build(e, direction)
        path = f"{OUT}/{e['slug']}.sqx"
        write_sqx(xml, path)
        z = zipfile.ZipFile(path)
        out = z.read("strategy_Portfolio.xml").decode("utf-8", "replace")
        ok = ("EnterAtMarket" in out) and ("StopLoss.StopLoss" in out) and ("SLPT.ATRBasedValue" in out)
        var = LONG_VAR if direction == "long" else SHORT_VAR
        ok = ok and (f'variable="{var}"' in out)
        print(f"{e['slug']:36s} {os.path.getsize(path):6d} B  {direction:5s} verificado={ok}")
    print(f"\n→ {len(todos)} estrategias en {OUT}")


if __name__ == "__main__":
    main()
