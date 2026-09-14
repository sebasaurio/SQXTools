"""Parser de Custom Projects de StrategyQuant (.cfx multi-task).

Un Custom Project (.cfx) es un ZIP con:
  - config.xml  : manifiesto <Project><Tasks><Task .../></Tasks> + <Databanks>
  - <type>-TaskN.xml : el XML de settings de cada task (Build, Retest, Filtering,
                       SaveToFiles, ClearDatabanks, GoToTask, ...)

Este módulo lee el manifiesto, parsea el digest de cada task y lo formatea
en Markdown legible por el agente (para `analyze` no alcanza: un project
no es un builder standalone, es un workflow completo).
"""
from __future__ import annotations

import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

from .parser import _element_to_dict, _parse_value

# Tipos de task cuyo XML se parsea en detalle
_DETAIL_TYPES = {"Build", "Retest", "Optimize"}

_TIME = 86400  # segs/día, para convertir tiempos tipo 72000 (SQ usa segs desde medianoche)


@dataclass
class ProjectTask:
    """Una task del workflow: attrs del manifiesto + digest de su XML."""
    index: int
    type: str
    name: str
    title: str
    active: bool
    task_xml: str
    template_file: str = ""
    digest: dict = field(default_factory=dict)

    def label(self) -> str:
        return self.title or self.name

    def cross_check(self) -> str:
        """Para Retest: qué cross-check tiene activo (use=true)."""
        ccs = self.digest.get("cross_checks") or {}
        active = ccs.get("active") or []
        return active[0]["name"] if active else ""


@dataclass
class ProjectFile:
    filename: str
    name: str
    version: str
    tasks: list[ProjectTask] = field(default_factory=list)
    databanks: list[dict] = field(default_factory=list)

    def by_type(self, t: str) -> list[ProjectTask]:
        return [x for x in self.tasks if x.type == t]


def parse_project(path: str | Path) -> ProjectFile:
    """Parsea un .cfx de Custom Project: manifiesto + digest de cada task."""
    p = Path(path)
    with zipfile.ZipFile(p) as z:
        names = z.namelist()
        if "config.xml" not in names:
            raise ValueError(f"No es un Custom Project (falta config.xml): {names}")
        manifest = ET.fromstring(z.read("config.xml"))
        cache: dict[str, ET.Element] = {}

        def load_task_xml(fname: str) -> ET.Element | None:
            if fname not in names:
                return None
            if fname not in cache:
                cache[fname] = ET.fromstring(z.read(fname))
            return cache[fname]

        proj = ProjectFile(
            filename=p.name,
            name=manifest.get("name", ""),
            version=manifest.get("version", ""),
        )

        db = manifest.find("Databanks")
        if db is not None:
            proj.databanks = [
                {"name": d.get("name", ""), "position": int(d.get("position", 0)),
                 "sync": d.get("syncType", "")}
                for d in db.findall("Databank")
            ]

        for i, t in enumerate(manifest.iter("Task"), start=1):
            task = ProjectTask(
                index=i,
                type=t.get("type", "?"),
                name=t.get("name", ""),
                title=t.get("title", "") or t.get("name", ""),
                active=t.get("active", "true").lower() == "true",
                task_xml=t.get("taskXMLFile", ""),
                template_file=t.get("templateFile", ""),
            )
            root = load_task_xml(task.task_xml)
            if root is not None:
                task.digest = _digest_task(task.type, root)
            proj.tasks.append(task)

    return proj


# ---------------------------------------------------------------- digests

def _digest_task(task_type: str, root: ET.Element) -> dict:
    settings = root if root.tag == "Settings" else (root.find("Settings") or root)
    d: dict = {}
    d["databanks"] = _digest_databanks(settings.find("Databanks"))
    if task_type in _DETAIL_TYPES:
        d["data"] = _digest_data(settings.find("Data"))
        d["cross_checks"] = _digest_cross_checks(settings.find("CrossChecks"))
    if task_type == "Build":
        d["what_to_build"] = _digest_what_to_build(settings.find("WhatToBuild"))
        d["rankings"] = _digest_rankings(settings.find("Rankings"))
        d["blocks"] = _digest_blocks(settings.find("Blocks"))
        d["trading"] = _digest_trading(settings.find("Options"))
    elif task_type == "Filtering":
        d["filtering"] = _digest_filtering(settings.find("Filtering"))
    elif task_type == "SaveToFiles":
        d["save"] = _digest_save(settings.find("SaveToFiles"))
    elif task_type == "ClearDatabanks":
        el = settings.find("ClearDatabanks")
        d["clears"] = [x.get("name", "") for x in el.findall("Databank")] if el is not None else []
    elif task_type == "GoToTask":
        el = settings.find("GoToTask")
        if el is not None:
            d["goto"] = el.get("task", "")
    return d


def _seconds_to_hhmm(v: str) -> str:
    try:
        s = int(v)
        return f"{s // 3600:02d}:{(s % 3600) // 60:02d}"
    except (ValueError, TypeError):
        return v


_TRADING_KEYS = [  # (clave, formato)
    ("DontTradeOnWeekends", None), ("ExitOnFriday", None),
    ("FridayExitTime", _seconds_to_hhmm), ("LimitTimeRange", None),
    ("SignalTimeRangeFrom", _seconds_to_hhmm), ("SignalTimeRangeTo", _seconds_to_hhmm),
    ("MaxTradesPerDay", None), ("MaximumOpenPositions", None),
    ("MaximumOpenLots", None), ("Session", None), ("ReservedBars", None),
]


def _digest_trading(options: ET.Element | None) -> dict:
    if options is None:
        return {}
    out: dict = {}
    for p in options.iter("Param"):
        k = p.get("key", "")
        for want, fmt in _TRADING_KEYS:
            if k == want:
                out[k] = fmt(p.text) if fmt else _parse_value(p.text)[0]
    return out


def _digest_data(data: ET.Element | None) -> dict:
    if data is None:
        return {}
    d: dict = {"oos_ranges": []}
    setup = data.find("Setups/Setup")
    if setup is not None:
        d["date_from"] = setup.get("dateFrom", "")
        d["date_to"] = setup.get("dateTo", "")
        d["engine"] = setup.get("engine", "")
        d["slippage"] = setup.get("slippage", "")
        chart = setup.find("Chart")
        if chart is not None:
            d["symbol"] = chart.get("symbol", "")
            d["timeframe"] = chart.get("timeframe", "")
            d["spread"] = chart.get("spread", "")
        swap = setup.find("Swap")
        if swap is not None and swap.get("use") == "true":
            d["swap"] = f"long {swap.get('long', '?')} / short {swap.get('short', '?')} pts"
    oos = data.find("OutOfSample")
    if oos is not None:
        for r in oos.findall("Range"):
            d["oos_ranges"].append({
                "from": r.get("dateFrom", ""), "to": r.get("dateTo", ""),
                "type": r.get("type", "oos"),
            })
    return d


def _digest_cross_checks(cc: ET.Element | None) -> dict:
    """Qué cross-checks están use=true y sus settings clave."""
    if cc is None:
        return {"use": False, "active": []}
    d: dict = {
        "use": cc.get("use", "false") == "true",
        "evaluate_all": cc.get("evaluateAll", "false") == "true",
        "active": [],
    }
    for child in cc:
        if child.get("use") == "true":
            info: dict = {"name": child.tag}
            # settings de aceptación clave
            for key in ("PctToPass", "ResultsCount", "StabilityRange", "thresholdPct"):
                el = child.find(f".//{key}")
                if el is not None and el.text:
                    info[key] = _parse_value(el.text)[0]
            # rangos de optimización walk-forward
            for p1, p2 in (("Param1", "Param2"),):
                a, b = child.find(f".//{p1}"), child.find(f".//{p2}")
                if a is not None and b is not None:
                    info["wf_window"] = f"{a.get('value', '?')}/{b.get('value', '?')}"
            m = child.find(".//Method[@use='true']")
            if m is not None:
                info["method"] = m.get("type", "")
            d["active"].append(info)
    return d


def _digest_databanks(db: ET.Element | None) -> dict:
    out: dict = {}
    for d in (db.findall("Databank") if db is not None else []):
        label = d.get("label", "").lower()
        role = ("input" if "input" in label else
                "output" if "output" in label else
                "source" if "source" in label else
                "target" if "target" in label else label.replace(" ", "_") or "other")
        out[role] = d.get("value", "")
    return out


def _digest_what_to_build(w: ET.Element | None) -> dict:
    if w is None:
        return {}
    d = _element_to_dict(w)
    if not isinstance(d, dict):
        return {}
    keep = {}
    for k in ("BuildingMode", "StrategyQL", "MaxConfigs", "StrategiesPerConfig",
              "MaxPopulations", "PopulationSize", "SaveStrategyAfterEachGeneration"):
        if k in d:
            keep[k] = d[k]
    return keep


def _digest_rankings(r: ET.Element | None) -> dict:
    if r is None:
        return {}
    d: dict = {"type": r.get("type", "")}
    fitness = r.find("Fitness")
    if fitness is not None:
        d["fitness"] = fitness.get("value", fitness.text or "")
    # filtros activos (Use="true")
    filters = []
    for f in r.iter():
        if f.tag in ("Filter", "RankingFilter") and f.get("Use", "").lower() == "true":
            cond = {c.tag: c.text for c in f if c.text and c.text.strip()}
            filters.append({"name": f.get("Column", f.get("Name", "?")), **cond})
    if filters:
        d["filters"] = filters
    return d


def _digest_blocks(blocks: ET.Element | None) -> dict:
    if blocks is None:
        return {}
    counts: dict[str, int] = {}
    total = active = 0
    for b in blocks.iter("Block"):
        total += 1
        cat = b.get("type", b.get("group", "?"))
        counts[cat] = counts.get(cat, 0) + 1
        if b.get("use", b.get("Use", "")).lower() == "true":
            active += 1
    return {"total": total, "active": active, "by_category": counts}


def _digest_filtering(f: ET.Element | None) -> dict:
    if f is None:
        return {}
    action = {1: "copy", 2: "move", 3: "delete"}.get(
        int(f.findtext("ActionType", "0") or 0), f.findtext("ActionType", "?"))
    n_cond = len(f.findall("Conditions/Condition")) or len(f.findall("Conditions/*"))
    return {
        "action": action,
        "max_strategies": f.findtext("MaxStrategies", "0"),
        "conditions_type": f.findtext("ConditionsType", "?"),
        "n_conditions": n_cond,
    }


def _digest_save(s: ET.Element | None) -> dict:
    if s is None:
        return {}
    d: dict = {}
    sc = s.find("SaveSourceCode")
    if sc is not None and (sc.text or "").lower() == "true":
        d["source_code"] = sc.get("type", "?")
    for tag, key in (("SaveInSqxFormat", "sqx"), ("DestDirectorySC", "dir_source_code"),
                     ("DestDirectorySqx", "dir_sqx"), ("Format", "format"),
                     ("Data", "data"), ("OverwriteFiles", "overwrite")):
        v = s.findtext(tag, "")
        if v:
            d[key] = v
    return d


# ---------------------------------------------------------------- formato

def format_project(proj: ProjectFile, max_tasks: int | None = None) -> str:
    """Markdown legible por el agente: workflow + digest por task."""
    L: list[str] = []
    L.append(f"# Custom Project: {proj.name}")
    L.append(f"Archivo: `{proj.filename}` · versión SQ {proj.version}")
    L.append(f"Tasks: {len(proj.tasks)} ({len(proj.by_type('Build'))} build, "
             f"{len(proj.by_type('Retest'))} retest, "
             f"{len(proj.by_type('Filtering'))} filtering, "
             f"{len(proj.tasks) - len(proj.by_type('Build')) - len(proj.by_type('Retest')) - len(proj.by_type('Filtering'))} otras)")
    L.append("")

    # ---- workflow en orden
    L.append("## Workflow (en orden de ejecución)")
    L.append("")
    for t in proj.tasks:
        mark = "" if t.active else " ⏸️ INACTIVA"
        extra = ""
        if t.type == "Build":
            extra = f" ← plantilla `{Path(t.template_file).name}`" if t.template_file else ""
        elif t.cross_check():
            extra = f" · cross-check: **{t.cross_check()}**"
        elif t.type == "Filtering":
            extra = f" · {t.digest.get('filtering', {}).get('action', '?')}" \
                    f" → {t.digest.get('databanks', {}).get('target', '?')}"
        elif t.type == "GoToTask":
            extra = f" → vuelve a **{t.digest.get('goto', '?')}** (loop)"
        L.append(f"{t.index}. **[{t.type}]** {t.label()}{extra}{mark}")
    L.append("")

    # ---- resumen del pipeline de robustez
    retests = [t for t in proj.tasks if t.type == "Retest" and t.cross_check()]
    if retests:
        L.append("## Pipeline de robustez (cadena de filtros)")
        L.append("")
        L.append("Cada Retest corre UN cross-check; los FAILED van a su databank, "
                 "los que pasan siguen al siguiente filtro:")
        L.append("")
        for t in retests:
            cc = t.digest["cross_checks"]["active"][0]
            name = cc["name"]
            detail = []
            for k in ("PctToPass", "wf_window", "thresholdPct", "method", "StabilityRange"):
                if k in cc:
                    detail.append(f"{k}={cc[k]}")
            L.append(f"- **{name}** ({t.label()}){' · ' + ', '.join(detail) if detail else ''}")
        L.append("")

    # ---- databanks del project
    if proj.databanks:
        L.append("## Databanks")
        L.append("")
        for d in proj.databanks:
            L.append(f"- `{d['name']}` (pos {d['position']}, {d['sync']})")
        L.append("")

    # ---- detalle por task
    detail_tasks = [t for t in proj.tasks if t.digest.get("data") or t.type in ("Filtering", "GoToTask")]
    if max_tasks:
        detail_tasks = detail_tasks[:max_tasks]
    for t in detail_tasks:
        L.append("---")
        L.append("")
        L.append(f"## Task {t.index}: [{t.type}] {t.label()}")
        L.append("")
        dg = t.digest
        if dg.get("data"):
            d = dg["data"]
            L.append(f"**Datos:** `{d.get('symbol', '?')}` {d.get('timeframe', '?')} · "
                     f"{d.get('date_from', '?')} → {d.get('date_to', '?')} · engine {d.get('engine', '?')} · "
                     f"slippage {d.get('slippage', '?')} · spread {d.get('spread', '?')}")
            if d.get("swap"):
                L.append(f"**Swap:** {d['swap']}")
            oos = d.get("oos_ranges") or []
            if oos:
                L.append("")
                L.append("**Rangos OOS:**")
                for r in oos:
                    kind = "IS-validation" if r["type"] == "isv" else "OOS"
                    L.append(f"- {r['from']} → {r['to']} ({kind})")
        if dg.get("trading"):
            L.append("")
            L.append("**Trading options:** " + " · ".join(
                f"{k}={v}" for k, v in dg["trading"].items()))
        if dg.get("what_to_build"):
            L.append("")
            L.append("**WhatToBuild:** " + " · ".join(
                f"{k}={v}" for k, v in dg["what_to_build"].items()))
        if dg.get("rankings"):
            r = dg["rankings"]
            L.append("")
            L.append(f"**Rankings:** type={r.get('type', '?')}"
                     + (f" · fitness={r['fitness']}" if r.get("fitness") else ""))
            for f_ in r.get("filters", []):
                L.append(f"  - filtro `{f_.get('name', '?')}`: " + " ".join(
                    f"{k}={v}" for k, v in f_.items() if k != "name"))
        if dg.get("blocks"):
            b = dg["blocks"]
            L.append("")
            L.append(f"**Blocks:** {b['active']}/{b['total']} activos · "
                     + " · ".join(f"{k}: {v}" for k, v in b["by_category"].items()))
        if dg.get("cross_checks"):
            cc = dg["cross_checks"]
            if cc["active"]:
                L.append("")
                L.append(f"**Cross-checks activos:** {[a['name'] for a in cc['active']]}")
        if dg.get("filtering"):
            f_ = dg["filtering"]
            src = dg.get("databanks", {}).get("source", "?")
            tgt = dg.get("databanks", {}).get("target", "?")
            L.append("")
            L.append(f"**Filtro:** {f_['action']} de `{src}` → `{tgt}` · "
                     f"{f_['n_conditions']} condición(es) · tipo {f_['conditions_type']}")
        if dg.get("save"):
            L.append("")
            L.append("**Export:** " + " · ".join(f"{k}={v}" for k, v in dg["save"].items()))
        if dg.get("clears"):
            L.append("")
            L.append("**Limpia databanks:** " + ", ".join(f"`{x}`" for x in dg["clears"]))
        if dg.get("goto"):
            L.append("")
            L.append(f"**Salta a:** {dg['goto']}")
        L.append("")

    return "\n".join(L)


def project_to_dict(proj: ProjectFile) -> dict:
    """Salida JSON-friendly (para --json y para el agente)."""
    return {
        "filename": proj.filename,
        "name": proj.name,
        "version": proj.version,
        "n_tasks": len(proj.tasks),
        "databanks": proj.databanks,
        "tasks": [
            {
                "index": t.index, "type": t.type, "name": t.name,
                "title": t.label(), "active": t.active,
                "cross_check": t.cross_check() or None,
                "digest": t.digest or None,
            }
            for t in proj.tasks
        ],
    }
