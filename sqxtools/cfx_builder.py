"""CFX Builder — aplica un perfil de configuración sobre un .cfx existente.

StrategyQuant guarda toda la config del builder en un `config.xml` dentro del ZIP.
Este módulo modifica SOLO los valores indicados, preservando intacto el resto del
archivo (bloques, recursos, databanks, etc.). Así el .cfx resultante es siempre
importable en StrategyQuant.

Formatos internos que maneja:
  - `<SLPTOptions><MinPTATRMultiple>2</MinPTATRMultiple>...`   → valor = texto del tag
  - `<RulesComplexity><Chart minConditions="1" .../></RulesComplexity>`  → atributo
  - `<Param key="MaxTradesPerDay" className="...">0</Param>`   → texto del Param
  - `<Rankings><FitnessCriteria>...<Ranking type="ReturnDDRatio"/>`      → atributo
  - `<Rankings><Conditions><Condition>...<Column-Value column="ProfitFactor"/>
     ...<Numeric-Value value="1.2"/></Condition>`              → atributo anidado
  - `<ExitTypes><Block key="ExitAfterBars.ExitAfterBars" probability="50" .../>` → atributo

Uso:
    from sqxtools.cfx_builder import apply_builder_profile
    apply_builder_profile("v5.cfx", "v6.cfx", "perfil.yaml")
"""

import difflib
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# Categorías de bloques dentro de Blocks/BuildingBlocks
BLOCK_CATEGORIES = ("signals", "indicators", "stopLimitBlocks")


def _clean(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def load_cfx_xml(path: str | Path) -> ET.Element:
    """Carga el árbol XML de un .cfx (ZIP con config.xml)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo: {p}")
    with zipfile.ZipFile(p) as z:
        if "config.xml" not in z.namelist():
            raise ValueError(f"{p.name} no contiene config.xml")
        with z.open("config.xml") as f:
            return ET.parse(f).getroot()


def write_cfx_xml(root: ET.Element, output_path: str | Path) -> Path:
    """Escribe el árbol XML como .cfx (ZIP con config.xml)."""
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("config.xml", "w") as f:
            ET.ElementTree(root).write(f, encoding="utf-8", xml_declaration=True)
    return out


# === Localizadores ===

def _find_section(root: ET.Element, name: str) -> ET.Element | None:
    """Busca una sección por nombre en cualquier profundidad."""
    for el in root.iter():
        if _clean(el.tag) == name:
            return el
    return None


def _set_section_tag(root: ET.Element, section: str, tag: str,
                     value: str, changes: list) -> bool:
    """Setea el texto de <tag> dentro de <section> (ej. SLPTOptions/MinPTATRMultiple)."""
    sec = _find_section(root, section)
    if sec is None:
        changes.append({"setting": f"{section}.{tag}", "status": "section_not_found"})
        return False
    for el in sec:
        if _clean(el.tag) == tag:
            old = el.text
            if old == value:
                changes.append({"setting": f"{section}.{tag}", "status": "unchanged", "value": value})
            else:
                el.text = value
                changes.append({"setting": f"{section}.{tag}", "status": "changed", "from": old, "to": value})
            return True
    changes.append({"setting": f"{section}.{tag}", "status": "tag_not_found"})
    return False


def _set_chart_attr(root: ET.Element, attr: str, value: str, changes: list,
                    chart_name: str = "Main chart") -> bool:
    """Setea un atributo de <Chart> dentro de <RulesComplexity>."""
    sec = _find_section(root, "RulesComplexity")
    if sec is None:
        changes.append({"setting": f"RulesComplexity.{attr}", "status": "section_not_found"})
        return False
    for el in sec.iter():
        if _clean(el.tag) != "Chart":
            continue
        if chart_name and el.get("name") != chart_name:
            continue
        old = el.get(attr)
        if old == value:
            changes.append({"setting": f"RulesComplexity.{attr}", "status": "unchanged", "value": value})
        else:
            el.set(attr, value)
            changes.append({"setting": f"RulesComplexity.{attr}", "status": "changed", "from": old, "to": value})
        return True
    changes.append({"setting": f"RulesComplexity.{attr}", "status": "chart_not_found"})
    return False


def _set_trading_option(root: ET.Element, key: str, value: str, changes: list) -> bool:
    """Setea el texto de un <Param key="..."> dentro de <BuildTradingOptions>."""
    sec = _find_section(root, "BuildTradingOptions")
    if sec is None:
        changes.append({"setting": f"BuildTradingOptions.{key}", "status": "section_not_found"})
        return False
    for el in sec.iter():
        if _clean(el.tag) == "Param" and el.get("key") == key:
            old = el.text
            if old == value:
                changes.append({"setting": key, "status": "unchanged", "value": value})
            else:
                el.text = value
                changes.append({"setting": key, "status": "changed", "from": old, "to": value})
            return True
    changes.append({"setting": key, "status": "param_not_found"})
    return False


def _rankings_section(root: ET.Element) -> ET.Element | None:
    """Devuelve la sección <Rankings> (no la de <CrossChecks>)."""
    for el in root.iter():
        if _clean(el.tag) == "Rankings":
            return el
    return None


def _set_fitness(root: ET.Element, ranking_type: str, changes: list) -> bool:
    """Cambia el criterio de fitness (<Ranking type="..."/>)."""
    sec = _rankings_section(root)
    if sec is None:
        changes.append({"setting": "FitnessCriteria", "status": "section_not_found"})
        return False
    for el in sec.iter():
        if _clean(el.tag) == "Ranking" and el.get("type"):
            old = el.get("type")
            if old == ranking_type:
                changes.append({"setting": "FitnessCriteria", "status": "unchanged", "value": ranking_type})
            else:
                el.set("type", ranking_type)
                changes.append({"setting": "FitnessCriteria", "status": "changed", "from": old, "to": ranking_type})
            return True
    changes.append({"setting": "FitnessCriteria", "status": "not_found"})
    return False


def _iter_ranking_conditions(root: ET.Element):
    """Itera las <Condition> dentro de <Rankings><Conditions>."""
    sec = _rankings_section(root)
    if sec is None:
        return
    conds = None
    for el in sec:
        if _clean(el.tag) == "Conditions":
            conds = el
            break
    if conds is None:
        return
    for cond in conds:
        if _clean(cond.tag) == "Condition":
            yield cond


def _condition_column(cond: ET.Element) -> str | None:
    """Devuelve el nombre de columna del lado izquierdo de una condición."""
    for el in cond.iter():
        if _clean(el.tag) == "Column-Value" and el.get("column"):
            return el.get("column")
    return None


def _condition_numeric_value(cond: ET.Element) -> str | None:
    """Devuelve el valor numérico del lado derecho, si lo hay."""
    for el in cond.iter():
        if _clean(el.tag) == "Numeric-Value":
            return el.get("value")
    return None


def _set_ranking_condition(root: ET.Element, column: str, value: str | None,
                           comparator: str | None, use: bool | None,
                           changes: list) -> bool:
    """Modifica una condición de ranking existente identificada por columna."""
    found = False
    for cond in _iter_ranking_conditions(root):
        if _condition_column(cond) != column:
            continue
        found = True
        detail = {"setting": f"Rankings.{column}", "changes": []}

        if use is not None:
            old_use = cond.get("use")
            new_use = "true" if use else "false"
            if old_use != new_use:
                cond.set("use", new_use)
                detail["changes"].append(f"use: {old_use} → {new_use}")

        if comparator is not None:
            for el in cond.iter():
                if _clean(el.tag) == "Comparator":
                    old_c = el.get("value")
                    if old_c != comparator:
                        el.set("value", comparator)
                        detail["changes"].append(f"comparator: {old_c} → {comparator}")
                    break

        if value is not None:
            for el in cond.iter():
                if _clean(el.tag) == "Numeric-Value":
                    old_v = el.get("value")
                    if old_v != value:
                        el.set("value", value)
                        detail["changes"].append(f"value: {old_v} → {value}")
                    break

        if detail["changes"]:
            detail["status"] = "changed"
        else:
            detail["status"] = "unchanged"
        changes.append(detail)
        break

    if not found:
        changes.append({"setting": f"Rankings.{column}", "status": "condition_not_found"})
    return found


def _add_ranking_condition(root: ET.Element, column: str, comparator: str,
                           value: str, changes: list) -> bool:
    """Activa una condición de ranking para `column`.

    IMPORTANTE: StrategyQuant re-instancia las condiciones construidas "a mano"
    desde la definición de la columna y **reinicia el valor al default**
    (p. ej. WinLossRatio → 1.2). Por eso NO se crean condiciones nuevas:
    se REUTILIZA una condición inactiva existente (cambiando su columna, comparador
    y valor), lo que preserva la estructura completa de atributos que SQ espera.
    """
    sec = _rankings_section(root)
    if sec is None:
        changes.append({"setting": f"Rankings.{column}", "status": "section_not_found"})
        return False

    conds = None
    for el in sec:
        if _clean(el.tag) == "Conditions":
            conds = el
            break
    if conds is None:
        changes.append({"setting": f"Rankings.{column}", "status": "conditions_not_found"})
        return False

    # No duplicar si ya existe
    for cond in _iter_ranking_conditions(root):
        if _condition_column(cond) == column:
            changes.append({"setting": f"Rankings.{column}", "status": "already_exists"})
            return True

    # Buscar una condición inactiva con lado derecho numérico para reutilizar
    donor = None
    for cond in _iter_ranking_conditions(root):
        if cond.get("use", "false") == "true":
            continue
        if _condition_numeric_value(cond) is None:
            continue
        donor = cond
        break

    if donor is None:
        changes.append({"setting": f"Rankings.{column}",
                        "status": "no_free_condition_slot"})
        return False

    # Repurposear el donante: activar, cambiar columna, comparador y valor
    prev_column = _condition_column(donor)
    donor.set("use", "true")

    for cv in donor.iter("Column-Value"):
        if cv.get("column"):
            cv.set("column", column)
            if cv.get("class"):
                cv.set("class", column)
            break

    for comp in donor.iter("Comparator"):
        comp.set("value", comparator)
        break

    for nv in donor.iter("Numeric-Value"):
        nv.set("value", value)
        break

    changes.append({"setting": f"Rankings.{column}", "status": "added",
                    "reused_condition": prev_column,
                    "comparator": comparator, "value": value})
    return True


def _set_exit_probability(root: ET.Element, block_key: str, value: str,
                          changes: list) -> bool:
    """Setea el atributo probability de un <Block> en <ExitTypes>."""
    sec = _find_section(root, "ExitTypes")
    if sec is None:
        changes.append({"setting": f"ExitTypes.{block_key}", "status": "section_not_found"})
        return False
    for el in sec:
        if _clean(el.tag) == "Block" and el.get("key") == block_key:
            old = el.get("probability")
            if old == value:
                changes.append({"setting": f"ExitTypes.{block_key}", "status": "unchanged", "value": value})
            else:
                el.set("probability", value)
                changes.append({"setting": f"ExitTypes.{block_key}", "status": "changed", "from": old, "to": value})
            return True
    changes.append({"setting": f"ExitTypes.{block_key}", "status": "block_not_found"})
    return False



def _iter_cfx_blocks(root: ET.Element, category: str | None = None):
    """Itera los <Block> de Blocks/BuildingBlocks (o de otra categoría del .cfx)."""
    blocks = _find_section(root, "BuildingBlocks")
    if blocks is None:
        return
    for el in blocks:
        if _clean(el.tag) != "Block":
            continue
        if category is not None and el.get("category") != category:
            continue
        yield el


def _cfx_block_keys(root: ET.Element, category: str) -> list[str]:
    """Keys válidas de una categoría dentro del .cfx."""
    return [el.get("key", "") for el in _iter_cfx_blocks(root, category)]


def _set_block_use(root: ET.Element, category: str, keys, use: bool,
                   changes: list, strict: bool = True) -> None:
    """Marca use=true/false en los bloques indicados de una categoría del .cfx.

    IMPORTANTE: activar un bloque en el .cfx es lo que hace que el builder lo USE
    durante un build. Modificar solo el .sqb (catálogo global) no basta.
    """
    keys = set(keys or [])
    if not keys:
        return

    available = set(_cfx_block_keys(root, category))
    missing = sorted(keys - available)
    if missing:
        for key in missing:
            sug = difflib.get_close_matches(key, sorted(available), n=1, cutoff=0.6)
            changes.append({
                "setting": f"blocks.{category}.{key}",
                "status": "block_not_found",
                "suggestion": sug[0] if sug else None,
            })
        if strict:
            detail = "\n".join(
                f"  - [{category}] '{k}'"
                + (f"  → ¿quisiste decir '{difflib.get_close_matches(k, sorted(available), n=1, cutoff=0.6)[0]}'?"
                   if difflib.get_close_matches(k, sorted(available), n=1, cutoff=0.6) else "")
                for k in missing
            )
            raise ValueError("Bloques inválidos en el .cfx:\n" + detail)

    done = 0
    for el in _iter_cfx_blocks(root, category):
        key = el.get("key", "")
        if key not in keys:
            continue
        new_use = "true" if use else "false"
        old = el.get("use", "false")
        if old != new_use:
            el.set("use", new_use)
            changes.append({"setting": f"blocks.{key}", "status": "changed",
                            "from": old, "to": new_use})
            done += 1
        else:
            changes.append({"setting": f"blocks.{key}", "status": "unchanged",
                            "value": new_use})


# === Perfiles de builder (YAML/JSON) ===

def load_builder_profile(path: str | Path) -> dict:
    """Carga un perfil de builder desde YAML o JSON."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el perfil: {p}")
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError("Perfil YAML pero pyyaml no está instalado (pip install pyyaml)")
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("El perfil de builder debe ser un objeto con secciones")
    return data


def _as_bool(v) -> str:
    return "true" if (v is True or str(v).lower() in ("true", "1", "yes", "sí", "si")) else "false"


def _as_num(v) -> str:
    """Formatea números sin .0 innecesario (1.0 → 1, 1.5 → 1.5)."""
    try:
        f = float(v)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(v)


def apply_builder_profile(
    template_path: str | Path,
    output_path: str | Path,
    profile: dict | str | Path,
    strict: bool = True,
) -> dict:
    """Aplica un perfil de builder sobre un .cfx y escribe el resultado.

    Args:
        strict: si True, aborta con ValueError si el perfil pide un bloque que no
            existe en el catálogo del .cfx (con sugerencia de corrección).

    Returns:
        {"output": str, "applied": int, "changes": [...], "warnings": [...]}
    """
    if isinstance(profile, (str, Path)):
        profile = load_builder_profile(profile)

    root = load_cfx_xml(template_path)
    changes: list = []

    # --- Risk / Reward (SLPTOptions) ---
    rr = profile.get("risk_reward") or {}
    if "limit_slpt_rrr" in rr:
        _set_section_tag(root, "SLPTOptions", "LimitSLPTRRR", _as_bool(rr["limit_slpt_rrr"]), changes)
    if "rrr_from" in rr:
        _set_section_tag(root, "SLPTOptions", "LimitSLPTRRRFrom", _as_num(rr["rrr_from"]), changes)
    if "rrr_to" in rr:
        _set_section_tag(root, "SLPTOptions", "LimitSLPTRRRTo", _as_num(rr["rrr_to"]), changes)
    for key, tag in (
        ("sl_atr_multiple_min", "MinSLATRMultiple"),
        ("sl_atr_multiple_max", "MaxSLATRMultiple"),
        ("pt_atr_multiple_min", "MinPTATRMultiple"),
        ("pt_atr_multiple_max", "MaxPTATRMultiple"),
        ("min_sl_pips", "MinSLInPips"),
        ("max_sl_pips", "MaxSLInPips"),
        ("min_pt_pips", "MinPTInPips"),
        ("max_pt_pips", "MaxPTInPips"),
    ):
        if key in rr:
            _set_section_tag(root, "SLPTOptions", tag, _as_num(rr[key]), changes)

    # --- Entradas (RulesComplexity) ---
    en = profile.get("entries") or {}
    for key, attr in (
        ("min_conditions", "minConditions"),
        ("max_conditions", "maxConditions"),
        ("min_exit_conditions", "minExitConditions"),
        ("max_exit_conditions", "maxExitConditions"),
        ("min_period", "minPeriod"),
        ("max_period", "maxPeriod"),
    ):
        if key in en:
            _set_chart_attr(root, attr, _as_num(en[key]), changes, chart_name=en.get("chart", "Main chart"))

    # --- Trading options ---
    tr = profile.get("trading") or {}
    for key, opt in (
        ("limit_time_range", "LimitTimeRange"),
        ("signal_time_from", "SignalTimeRangeFrom"),
        ("signal_time_to", "SignalTimeRangeTo"),
        ("max_trades_per_day", "MaxTradesPerDay"),
        ("dont_trade_weekends", "DontTradeOnWeekends"),
        ("exit_on_friday", "ExitOnFriday"),
        ("friday_exit_time", "FridayExitTime"),
        ("max_open_positions_short", "PickerMaxOpenPositionsShort"),
        ("max_open_positions_long", "PickerMaxOpenPositionsLong"),
        ("realistic_gaps_handling", "RealisticGapsHandling"),
        ("exit_at_end_of_day", "ExitAtEndOfDay"),
        ("min_sl", "MinimumSL"),
        ("max_sl", "MaximumSL"),
        ("min_pt", "MinimumPT"),
        ("max_pt", "MaximumPT"),
    ):
        if key in tr:
            raw = tr[key]
            val = _as_bool(raw) if isinstance(raw, bool) else _as_num(raw)
            _set_trading_option(root, opt, val, changes)

    # --- Rankings ---
    rk = profile.get("rankings") or {}
    if "fitness" in rk:
        _set_fitness(root, str(rk["fitness"]), changes)

    for key, col in (
        ("return_dd_ratio_min", "ReturnDDRatio"),
        ("profit_factor_min", "ProfitFactor"),
        ("win_loss_ratio_min", "WinLossRatio"),
        ("percent_profitable_min", "PercentProfitable"),
        ("number_of_trades_min", "NumberOfTrades"),
        ("sharpe_ratio_min", "SharpeRatio"),
        ("drawdown_pct_max", "DrawdownPct"),
        ("rsquared_min", "RSquared"),
    ):
        if key not in rk:
            continue
        comparator = "<=" if col in ("DrawdownPct",) else ">="
        value = _as_num(rk[key])
        # Si la condición ya existe la modifica; si no, la agrega activa
        if not _set_ranking_condition(root, col, value, comparator, True, changes):
            changes.pop()  # descarta el "condition_not_found"
            _add_ranking_condition(root, col, comparator, value, changes)

    # --- Exits ---
    ex = profile.get("exits") or {}
    for key, block in (
        ("exit_after_bars_probability", "ExitAfterBars.ExitAfterBars"),
        ("move_sl2be_probability", "MoveSL2BE.MoveSL2BE"),
        ("profit_target_probability", "ProfitTarget.ProfitTarget"),
        ("stop_loss_probability", "StopLoss.StopLoss"),
        ("trailing_stop_probability", "TrailingStop.TrailingStop"),
    ):
        if key in ex:
            _set_exit_probability(root, block, _as_num(ex[key]), changes)

    # --- Bloques del builder (activar/desactivar señales, indicadores, stops) ---
    bl = profile.get("blocks") or {}
    if isinstance(bl, dict):
        for cat in BLOCK_CATEGORIES:
            add_key = f"add_{cat}"
            if add_key in bl:
                _set_block_use(root, cat, bl[add_key], True, changes, strict=strict)
            rem_key = f"remove_{cat}"
            if rem_key in bl:
                _set_block_use(root, cat, bl[rem_key], False, changes, strict=strict)
        if "set_signals" in bl:
            # Lista exacta: activa las indicadas y desactiva el resto
            wanted = set(bl["set_signals"])
            _set_block_use(root, "signals", wanted, True, changes, strict=strict)
            for el in _iter_cfx_blocks(root, "signals"):
                if el.get("key") not in wanted and el.get("use") == "true":
                    el.set("use", "false")
                    changes.append({"setting": f"blocks.{el.get('key')}",
                                    "status": "changed", "from": "true", "to": "false"})

    # Detectar claves desconocidas en el perfil (se ignorarían en silencio)
    known = {
        "risk_reward": {"limit_slpt_rrr", "rrr_from", "rrr_to",
                        "sl_atr_multiple_min", "sl_atr_multiple_max",
                        "pt_atr_multiple_min", "pt_atr_multiple_max",
                        "min_sl_pips", "max_sl_pips", "min_pt_pips", "max_pt_pips"},
        "entries": {"min_conditions", "max_conditions", "min_exit_conditions",
                    "max_exit_conditions", "min_period", "max_period", "chart"},
        "trading": {"limit_time_range", "signal_time_from", "signal_time_to",
                    "max_trades_per_day", "dont_trade_weekends", "exit_on_friday",
                    "friday_exit_time", "max_open_positions_short", "max_open_positions_long",
                    "realistic_gaps_handling", "exit_at_end_of_day",
                    "min_sl", "max_sl", "min_pt", "max_pt"},
        "rankings": {"fitness", "return_dd_ratio_min", "profit_factor_min",
                     "win_loss_ratio_min", "percent_profitable_min",
                     "number_of_trades_min", "sharpe_ratio_min",
                     "drawdown_pct_max", "rsquared_min"},
        "exits": {"exit_after_bars_probability", "move_sl2be_probability",
                  "profit_target_probability", "stop_loss_probability",
                  "trailing_stop_probability"},
    }
    # Claves válidas dentro de la sección 'blocks'
    known_block_keys = {
        f"{pre}_{cat}"
        for pre in ("add", "remove")
        for cat in BLOCK_CATEGORIES
    } | {"set_signals"}
    meta_keys = {"name", "description", "symbol", "timeframe"}
    unknown: list = []
    for section, values in profile.items():
        if section in meta_keys:
            continue
        if section == "blocks":
            # Validado dentro de _set_block_use (contra el catálogo del .cfx)
            if isinstance(values, dict):
                for key in values:
                    if key not in known_block_keys:
                        unknown.append(f"blocks.{key}")
            continue
        if section not in known:
            unknown.append(f"sección desconocida: '{section}'")
            continue
        if not isinstance(values, dict):
            continue
        valid_keys = known_block_keys if section == "blocks" else known[section]
        for key in values:
            if key not in valid_keys:
                unknown.append(f"{section}.{key}")

    out = write_cfx_xml(root, output_path)

    applied = sum(1 for c in changes if c.get("status") in ("changed", "added"))
    warnings = [f"{c['setting']}: {c['status']}"
                for c in changes if c.get("status") in
                ("section_not_found", "tag_not_found", "param_not_found",
                 "chart_not_found", "block_not_found", "not_found", "conditions_not_found")]
    warnings += [f"ajuste desconocido ignorado: {u}" for u in unknown]

    return {
        "output": str(out),
        "applied": applied,
        "changes": changes,
        "warnings": warnings,
    }
