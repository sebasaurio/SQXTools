"""Inspección universal y validación de Custom Projects.

`inspect_file` — enrutamiento automático: dado CUALQUIER archivo SQ (.cfx project,
builder, .sqb), detecta qué es y genera el resumen correcto sin que el agente tenga
que adivinar. Es la puerta de entrada estándar para archivos nuevos.

`check_project` — validaciones mecánicas del workflow de un Custom Project:
flujo de databanks, cross-checks sin Filtering emparejado, OOS desalineados,
loop del GoToTask, plantillas inexistentes, trading options inconsistentes.
"""
from __future__ import annotations

import zipfile
from datetime import date
from pathlib import Path
from xml.etree import ElementTree as ET

from .parser import parse_cfx
from .project_parser import ProjectFile, parse_project


def sniff(path: str | Path) -> dict:
    """Detecta el tipo de archivo SQ por su contenido (no por la extensión)."""
    p = Path(path)
    if not p.exists():
        return {"kind": "missing", "path": str(p)}
    try:
        with zipfile.ZipFile(p) as z:
            names = z.namelist()
            if "config.xml" in names:
                root = ET.fromstring(z.read("config.xml"))
                if root.tag == "Project" and root.find("Tasks") is not None:
                    n_tasks = len(list(root.iter("Task")))
                    return {"kind": "project", "path": str(p), "name": root.get("name", ""),
                            "version": root.get("version", ""), "n_tasks": n_tasks}
                if root.tag == "Blocks":
                    return {"kind": "sqb", "path": str(p),
                            "n_blocks": len(list(root.iter("Block")))}
                return {"kind": "builder", "path": str(p), "type": root.get("type", "build"),
                        "version": root.get("version", "")}
            sqb_root = None
            for n in names:
                if n.endswith(".xml"):
                    r = ET.fromstring(z.read(n))
                    if len(list(r.iter("Block"))) > 0:
                        sqb_root = r
                        break
            if sqb_root is not None:
                return {"kind": "sqb", "path": str(p), "n_blocks": len(list(sqb_root.iter("Block")))}
    except zipfile.BadZipFile:
        return {"kind": "unknown", "path": str(p),
                "reason": "no es un ZIP (¿.sqx compilado, .str, otro formato?)"}
    return {"kind": "unknown", "path": str(p), "entries": names[:10]}


def inspect_file(path: str | Path) -> dict:
    """Inspecciona cualquier archivo SQ y devuelve su resumen correcto."""
    info = sniff(path)
    kind = info["kind"]
    result: dict = {"file": info["path"], "kind": kind}
    if kind == "missing" or kind == "unknown":
        result.update(info)
        return result
    if kind == "project":
        proj = parse_project(path)
        result["project"] = project_to_dict_lite(proj)
        result["checks"] = [c.to_dict() for c in check_project(proj)]
        return result
    if kind == "builder":
        cfg = parse_cfx(path)
        result["summary"] = {
            "filename": cfg.filename,
            "type": str(cfg.cfx_type),
            "version": cfg.version,
            "blocks": getattr(cfg.blocks, "get", lambda k, d=None: None)("building_blocks") is not None and sum(
                1 for b in cfg.blocks.get("building_blocks", []) if b.get("use")) or None,
        }
        # resumen compacto reutilizando el analizador
        from .analyzer import summarize
        try:
            s = summarize(cfg)
            keep = ("type", "blocks_summary", "risk_reward", "rankings", "dates",
                    "trading_options_summary", "exits_summary")
            result["summary"] = {k: s[k] for k in keep if k in s}
        except Exception:
            pass
        return result
    if kind == "sqb":
        from .sqb_parser import get_block_summary, parse_sqb
        sqb = parse_sqb(path)
        result["summary"] = get_block_summary(sqb)
        return result
    return result


def project_to_dict_lite(proj: ProjectFile) -> dict:
    """Versión compacta del project para inspect."""
    return {
        "name": proj.name,
        "version": proj.version,
        "n_tasks": len(proj.tasks),
        "active_tasks": sum(1 for t in proj.tasks if t.active),
        "databanks": len(proj.databanks),
        "workflow": [
            {"i": t.index, "type": t.type, "title": t.label(), "active": t.active,
             "check": t.cross_check() or None}
            for t in proj.tasks
        ],
    }


# ---------------------------------------------------------------- checks

class Finding:
    """Un problema detectado en el workflow."""

    def __init__(self, severity: str, task: int | None, code: str, message: str,
                 suggestion: str = ""):
        self.severity = severity      # "error" | "warning" | "info"
        self.task = task
        self.code = code
        self.message = message
        self.suggestion = suggestion

    def to_dict(self) -> dict:
        d: dict = {"severity": self.severity, "code": self.code, "message": self.message}
        if self.task is not None:
            d["task"] = self.task
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d

    def __repr__(self) -> str:
        loc = f" (task {self.task})" if self.task else ""
        sug = f" → {self.suggestion}" if self.suggestion else ""
        return f"[{self.severity.upper()}]{loc} {self.code}: {self.message}{sug}"


def _parse_sq_date(s: str) -> date | None:
    try:
        y, m, d = s.split(".")
        return date(int(y), int(m), int(d))
    except (ValueError, AttributeError):
        return None


def check_project(proj: ProjectFile) -> list[Finding]:
    """Validaciones mecánicas sobre el workflow. Read-only, sin falsos positivos
    de diseño: lo que depende del estado interno de SQ se marca como 'info'."""
    F: list[Finding] = []
    active = [t for t in proj.tasks if t.active]

    # 1. Cada Retest activo con cross-check debe tener su Filtering emparejado
    for t in active:
        if t.type == "Retest" and t.cross_check():
            nxt = proj.tasks[t.index] if t.index < len(proj.tasks) else None  # 1-indexed
            if not (nxt and nxt.type == "Filtering" and nxt.active):
                F.append(Finding(
                    "warning", t.index, "retest_sin_filtering",
                    f"Retest '{t.label()}' ({t.cross_check()}) no sigue de un Filtering activo",
                    "agregar o activar el Filtering que separe los FAILED"))

    # 2. Loop del GoToTask — el loop activo se valida estricto; el inactivo que apunta
    #    a un Build también advierte, porque el usuario activa/desactiva tasks entre corridas
    for t in proj.tasks:
        if t.type != "GoToTask" or not t.digest.get("goto"):
            continue
        target = next((x for x in proj.tasks if x.name == t.digest["goto"]), None)
        if t.active:
            if target is None:
                F.append(Finding("error", t.index, "goto_inexistente",
                                 f"GoToTask apunta a '{t.digest['goto']}' que no existe"))
            elif not target.active:
                F.append(Finding("error", t.index, "goto_a_inactiva",
                                 f"GoToTask apunta a '{target.label()}' que está INACTIVA",
                                 f"activar task {target.index} o cambiar el destino del loop"))
        if target and target.type == "Build" and not any(
                x.type == "ClearDatabanks" and x.active for x in active):
            has_clear = any(x.type == "ClearDatabanks" for x in proj.tasks)
            msg = ("loop Build→GoTo sin ClearDatabanks activo: los resultados de "
                   "iteraciones anteriores se mezclan con los nuevos")
            if has_clear:
                F.append(Finding("warning", t.index, "cleardatabanks_inactivo", msg,
                                 f"activar task {[x.index for x in proj.tasks if x.type=='ClearDatabanks'][0]}"))
            else:
                F.append(Finding("warning", t.index, "sin_cleardatabanks", msg,
                                 "agregar task ClearDatabanks al inicio del loop"))

    # 3. Flujo de databanks Build→Retest
    builds = [t for t in active if t.type == "Build"]
    retests = [t for t in active if t.type == "Retest"]
    for b in builds:
        out_db = b.digest.get("databanks", {}).get("output", "")
        for r in retests:
            in_db = r.digest.get("databanks", {}).get("input", "")
            if out_db and in_db and out_db != in_db:
                # puede ser legítimo (copias manuales en SQ); marcar como info
                F.append(Finding(
                    "info", b.index, "databank_desalineado",
                    f"Build '{b.label()}' escribe a '{out_db}' pero Retest '{r.label()}' lee '{in_db}'",
                    "verificar en SQ que haya copia/movimiento entre databanks"))

    # 4. OOS desalineados entre Build activo y Retests activos
    build_ranges = None
    for b in builds:
        oos = (b.digest.get("data") or {}).get("oos_ranges") or []
        build_ranges = [(r["from"], r["to"]) for r in oos]
    if build_ranges:
        for r in retests:
            oos = (r.digest.get("data") or {}).get("oos_ranges") or []
            rr = [(x["from"], x["to"]) for x in oos]
            if rr and rr != build_ranges:
                diffs = sum(1 for a, b_ in zip(build_ranges, rr) if a != b_)
                if diffs:
                    F.append(Finding(
                        "info", r.index, "oos_desalineado",
                        f"Retest '{r.label()}' valida sobre {diffs}/{len(rr)} rangos distintos al Build",
                        "unificar cortes ISV/OOS para que el PASS sea homogéneo"))

    # 5. Plantilla del Build: ruta de Windows no resoluble aquí → solo avisar si vacía
    for b in builds:
        if not b.template_file:
            F.append(Finding("info", b.index, "build_sin_plantilla",
                             f"Build '{b.label()}' no declara templateFile"))

    # 6. Trading options inconsistentes entre Build y Retests activos
    build_trading = next(((b.digest.get("trading") or {}) for b in builds), {})
    if build_trading:
        for r in retests:
            rt = r.digest.get("trading") or {}
            if not rt:
                continue
            for k in ("LimitTimeRange", "SignalTimeRangeFrom", "SignalTimeRangeTo"):
                if k in build_trading and k in rt and build_trading[k] != rt[k]:
                    F.append(Finding(
                        "warning", r.index, "ventana_desalineada",
                        f"Retest '{r.label()}': {k}={rt[k]} difiere del Build ({build_trading[k]})",
                        "alinear la ventana horaria para que el retest mida lo que el build genera"))
    return F


def format_findings(findings: list[Finding]) -> str:
    if not findings:
        return "✅ Sin problemas detectados."
    icons = {"error": "🔴", "warning": "🟠", "info": "🟡"}
    lines = [f"{icons[f.severity]} [{f.code}] {f}" for f in findings]
    n_err = sum(1 for f in findings if f.severity == "error")
    n_warn = sum(1 for f in findings if f.severity == "warning")
    lines.append(f"\n{n_err} error(es), {n_warn} warning(s)")
    return "\n".join(lines)
