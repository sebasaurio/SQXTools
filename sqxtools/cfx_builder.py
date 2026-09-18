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

import copy
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


# === Condiciones de filtro genéricas (Rankings y BuildMode) ===
#
# Rankings y BuildMode comparten la MISMA estructura de <Condition>. Lo que cambia
# es el contenedor y el momento en que SQ los evalúa:
#   - Rankings  → filtros de salida al databank (después del build)
#   - BuildMode → condiciones de supervivencia del genético (durante la evolución)
# Filtrar en el genético evita gastar generaciones en estrategias que el ranking
# va a descartar al final.

# Claves escalares del perfil para las condiciones del genético → (columna, comparador)
GENETIC_KEYS: dict[str, tuple[str, str]] = {
    "profit_factor_min": ("ProfitFactor", ">="),
    "number_of_trades_min": ("NumberOfTrades", ">="),
    "avg_bars_in_trade_min": ("AvgBarsInTrade", ">="),
    "sharpe_ratio_min": ("SharpeRatio", ">="),
    "return_dd_ratio_min": ("ReturnDDRatio", ">="),
    "win_loss_ratio_min": ("WinLossRatio", ">="),
    "rsquared_min": ("RSquared", ">="),
    "percent_profitable_min": ("PercentProfitable", ">="),
    "sqn_score_min": ("SQNScore", ">="),
    "winning_pct_min": ("WinningPct", ">="),
    "cagr_min": ("CAGR", ">="),
    "stagnation_max": ("Stagnation", "<="),
    "max_consec_losses_max": ("MaxConsecLosses", "<="),
}

# Columnas cuyo valor es entero (afecta el atributo `format` de la condición)
INTEGER_COLUMNS = frozenset({
    "NumberOfTrades", "MaxConsecLosses", "Stagnation", "BarCount", "MaxTradesPerDay",
})


def _column_format(column: str) -> str:
    return "Integer" if column in INTEGER_COLUMNS else "Decimal2"


def _buildmode_section(root: ET.Element) -> ET.Element | None:
    """Devuelve la sección <BuildMode> (configuración del genético)."""
    for el in root.iter():
        if _clean(el.tag) == "BuildMode":
            return el
    return None


def _filter_section(root: ET.Element, section: str) -> ET.Element | None:
    """Sección contenedora de condiciones de filtro: 'Rankings' o 'BuildMode'."""
    if section == "Rankings":
        return _rankings_section(root)
    if section == "BuildMode":
        return _buildmode_section(root)
    return None


def _conditions_container(root: ET.Element, section: str) -> ET.Element | None:
    """Devuelve el <Conditions> DIRECTO de la sección indicada.

    Ojo: `_find_section(root, "Conditions")` devolvería el de <Rankings> siempre,
    que es el primer <Conditions> del documento. Hay que scopearlo a su sección.
    """
    sec = _filter_section(root, section)
    if sec is None:
        return None
    for el in sec:
        if _clean(el.tag) == "Conditions":
            return el
    return None


def _iter_filter_conditions(root: ET.Element, section: str):
    """Itera las <Condition> de `section` ('Rankings' o 'BuildMode')."""
    conds = _conditions_container(root, section)
    if conds is None:
        return
    for cond in conds:
        if _clean(cond.tag) == "Condition":
            yield cond


def _left_column_value(cond: ET.Element) -> ET.Element | None:
    """Primer <Column-Value> dentro de <Left-Side> (el lado que define la métrica).

    Se limita a Left-Side a propósito: en condiciones con dos columnas (comparativas
    IS vs OOS) el Right-Side tiene su propio sampleType y no debe tocarse.
    """
    for side in cond:
        if _clean(side.tag) != "Left-Side":
            continue
        for el in side.iter():
            if _clean(el.tag) == "Column-Value" and el.get("column"):
                return el
    return None


def _set_sample_type(root: ET.Element, section: str, value: str,
                     changes: list, columns=None) -> bool:
    """Fija el `sampleType` de las condiciones ACTIVAS de una sección.

    sampleType: 10 = In-Sample · 20 = Out-of-Sample · 127 = IS+OOS combinados.

    Por qué importa: una condición en 127 filtra sobre IS **y** OOS a la vez, así
    que el out-of-sample participa de la selección y deja de ser un juez
    independiente. Para validar de verdad, los filtros van en 10 (solo IS).
    """
    n_changed = n_same = 0
    for cond in _iter_filter_conditions(root, section):
        if cond.get("use", "false") != "true":
            continue
        if columns is not None and _condition_column(cond) not in columns:
            continue
        cv = _left_column_value(cond)
        if cv is None or not cv.get("sampleType"):
            continue
        if cv.get("sampleType") == value:
            n_same += 1
        else:
            cv.set("sampleType", value)
            n_changed += 1

    if n_changed == 0 and n_same == 0:
        changes.append({"setting": f"{section}.sample_type", "status": "condition_not_found"})
        return False
    changes.append({"setting": f"{section}.sample_type",
                    "status": "changed" if n_changed else "unchanged",
                    "to": value, "changed_count": n_changed, "already": n_same})
    return True


def _repurpose_condition(cond: ET.Element, column: str, comparator: str,
                         value: str) -> None:
    """Reescribe una condición existente para que mida `column`."""
    cond.set("use", "true")
    cv = _left_column_value(cond)
    if cv is not None:
        cv.set("column", column)
        if cv.get("class"):
            cv.set("class", column)
        if cv.get("format"):
            cv.set("format", _column_format(column))
    for el in cond.iter():
        if _clean(el.tag) == "Comparator":
            el.set("value", comparator)
            break
    for el in cond.iter():
        if _clean(el.tag) == "Numeric-Value":
            el.set("value", value)
            break


def _apply_condition(root: ET.Element, section: str, column: str, comparator: str,
                     value: str, use: bool, changes: list) -> bool:
    """Setea o agrega una condición de filtro en 'Rankings' o 'BuildMode'.

    Orden de preferencia:
      1. Si la columna ya existe → se modifica (use / comparador / valor).
      2. Si no, se REUTILIZA un slot inactivo con lado derecho numérico (mismo
         criterio que `_add_ranking_condition`: SQ re-instancia las condiciones
         construidas a mano y reinicia su valor al default).
      3. Si no hay slot libre, se CLONA una condición numérica existente. Un clon
         conserva todos los atributos que SQ espera, pero el re-instanciado puede
         resetearlo igual: se reporta como `cloned_needs_check` para verificar en la UI.
    """
    # 1. Existente
    for cond in _iter_filter_conditions(root, section):
        if _condition_column(cond) != column:
            continue
        detail: dict = {"setting": f"{section}.{column}", "changes": []}
        if use is not None:
            new_use = "true" if use else "false"
            if cond.get("use") != new_use:
                detail["changes"].append(f"use: {cond.get('use')} → {new_use}")
                cond.set("use", new_use)
        if comparator is not None:
            for el in cond.iter():
                if _clean(el.tag) == "Comparator":
                    if el.get("value") != comparator:
                        detail["changes"].append(f"comparator: {el.get('value')} → {comparator}")
                        el.set("value", comparator)
                    break
        if value is not None:
            for el in cond.iter():
                if _clean(el.tag) == "Numeric-Value":
                    if el.get("value") != value:
                        detail["changes"].append(f"value: {el.get('value')} → {value}")
                        el.set("value", value)
                    break
        detail["status"] = "changed" if detail["changes"] else "unchanged"
        changes.append(detail)
        return True

    # 2. Reutilizar slot inactivo con valor numérico
    for cond in _iter_filter_conditions(root, section):
        if cond.get("use", "false") == "true":
            continue
        if _condition_numeric_value(cond) is None:
            continue
        prev_column = _condition_column(cond)
        _repurpose_condition(cond, column, comparator, value)
        changes.append({"setting": f"{section}.{column}", "status": "added",
                        "reused_condition": prev_column,
                        "comparator": comparator, "value": value})
        return True

    # 3. Clonar una condición numérica (SQ puede resetearla — verificar en la UI)
    proto = None
    for cond in _iter_filter_conditions(root, section):
        if _condition_numeric_value(cond) is not None:
            proto = cond
            break
    container = _conditions_container(root, section)
    if proto is None or container is None:
        changes.append({"setting": f"{section}.{column}",
                        "status": "conditions_not_found"})
        return False

    donor = copy.deepcopy(proto)
    container.append(donor)
    _repurpose_condition(donor, column, comparator, value)
    changes.append({"setting": f"{section}.{column}", "status": "cloned_needs_check",
                    "cloned_from": _condition_column(proto),
                    "comparator": comparator, "value": value})
    return True


# === Período de datos: In-Sample / Out-of-Sample ===

def _norm_date(value) -> str:
    """Normaliza una fecha al formato de StrategyQuant: 2020-01-01 → 2020.01.01."""
    return str(value).strip().replace("-", ".").replace("/", ".")


def _set_data_dates(root: ET.Element, date_from, date_to, changes: list) -> bool:
    """Fija el rango completo testeado (<Setup dateFrom/dateTo>)."""
    setups = [el for el in root.iter() if _clean(el.tag) == "Setup"]
    if not setups:
        changes.append({"setting": "Data.date_from", "status": "section_not_found"})
        return False
    for setup in setups:
        if date_from is not None:
            setup.set("dateFrom", _norm_date(date_from))
        if date_to is not None:
            setup.set("dateTo", _norm_date(date_to))
    changes.append({"setting": "Data.date_from/date_to", "status": "changed",
                    "from": _norm_date(date_from), "to": _norm_date(date_to),
                    "setups": len(setups)})
    return True


def _rewrite_out_of_sample(root: ET.Element, ranges, changes: list) -> bool:
    """Reescribe la partición IS/OOS de <OutOfSample>.

    Cada rango: {"from": "2020-01-01", "to": "2024-01-09", "type": "isv"} donde
    `type: isv` marca In-Sample (validación) y su ausencia marca Out-of-Sample.
    """
    oos = None
    for el in root.iter():
        if _clean(el.tag) == "OutOfSample":
            oos = el
            break
    if oos is None:
        changes.append({"setting": "Data.out_of_sample", "status": "section_not_found"})
        return False
    if not isinstance(ranges, list):
        changes.append({"setting": "Data.out_of_sample", "status": "invalid_range"})
        return False

    old = [f"{r.get('dateFrom')}→{r.get('dateTo')}"
           for r in oos if _clean(r.tag) == "Range"]
    for r in list(oos):
        if _clean(r.tag) == "Range":
            oos.remove(r)

    applied = []
    for spec in ranges:
        if not isinstance(spec, dict) or "from" not in spec or "to" not in spec:
            changes.append({"setting": "Data.out_of_sample", "status": "invalid_range"})
            continue
        r = ET.SubElement(oos, "Range")
        r.set("dateFrom", _norm_date(spec["from"]))
        r.set("dateTo", _norm_date(spec["to"]))
        if spec.get("type"):
            r.set("type", str(spec["type"]))
        applied.append(f"{_norm_date(spec['from'])}→{_norm_date(spec['to'])}"
                       + (" [IS]" if spec.get("type") else " [OOS]"))

    changes.append({"setting": "Data.out_of_sample", "status": "changed",
                    "from": old, "to": applied})
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

def _set_block_fixed_params(root: ET.Element, category: str, spec: dict,
                            changes: list, strict: bool = True) -> None:
    """Fija los parámetros de un bloque con un set predefinido de StrategyQuant.

    `spec` = `{"Prices.SessionLow": {"#StartHours#": 20, "#EndHours#": 12}}`.

    Por qué hace falta: los parámetros de los bloques vienen con
    `generation="random"`, así que el builder los sortea. Sin fijarlos, un bloque
    como `Prices.SessionLow` (horas de inicio/fin 0–23) nunca representa el rango
    overnight que se quiere probar. El set `<Predefined><Params>` con
    `generation="fixed" defaultValue` es el mecanismo de SQ para eso.
    """
    blocks = {el.get("key"): el for el in _iter_cfx_blocks(root, category)}
    for key, params in spec.items():
        el = blocks.get(key)
        if el is None:
            if strict:
                raise ValueError(
                    f"Bloque desconocido en la categoría '{category}': {key}")
            continue
        generated = el.find("Generated")
        proto = {}
        if generated is not None:
            proto = {p.get("key"): p for p in generated.findall("Param")}
        unknown = [k for k in params if k not in proto]
        if unknown and strict:
            raise ValueError(
                f"{key}: parámetros inexistentes {unknown}. "
                f"Disponibles: {sorted(proto)}")
        pre = el.find("Predefined")
        if pre is None:
            pre = ET.SubElement(el, "Predefined")
        for child in list(pre):
            pre.remove(child)
        pre.set("changed", "true")
        ps = ET.SubElement(pre, "Params")
        ps.set("name", "Fixed")
        ps.set("weight", "10")
        # Se copian TODOS los parámetros del bloque y se sobrescriben los pedidos:
        # SQ espera el juego completo, no solo los modificados.
        for pk, src in proto.items():
            p = ET.SubElement(ps, "Param")
            p.set("key", pk)
            p.set("name", src.get("name", pk))
            p.set("type", src.get("type", "int"))
            if pk in params:
                p.set("generation", "fixed")
                p.set("defaultValue", str(params[pk]))
            else:
                for a in ("generation", "minValue", "maxValue", "step", "allCharts"):
                    if src.get(a) is not None:
                        p.set(a, src.get(a))
        changes.append({"setting": f"blocks.{key}.fixed_params", "status": "changed",
                        "from": "random", "to": str(params)})


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
        ("sqn_score_min", "SQNScore"),
        ("sqn_min", "SQN"),
    ):
        if key not in rk:
            continue
        comparator = "<=" if col in ("DrawdownPct",) else ">="
        value = _as_num(rk[key])
        # Si la condición ya existe la modifica; si no, la agrega activa
        if not _set_ranking_condition(root, col, value, comparator, True, changes):
            changes.pop()  # descarta el "condition_not_found"
            _add_ranking_condition(root, col, comparator, value, changes)

    # --- Genético: condiciones de supervivencia del BuildMode ---
    # Son DISTINTAS de las de Ranking: el GA las evalúa por generación. Alinearlas
    # con el ranking evita gastar generaciones en estrategias que se descartan al final.
    ge = profile.get("genetic") or {}
    for key, (col, comp) in GENETIC_KEYS.items():
        if key in ge:
            _apply_condition(root, "BuildMode", col, comp, _as_num(ge[key]), True, changes)

    # --- sampleType: filtrar solo en In-Sample (10) y dejar el OOS limpio ---
    # 10 = IS · 20 = OOS · 127 = IS+OOS. Va DESPUÉS de setear condiciones para
    # alcanzar también las que se acaban de agregar/reutilizar.
    if "sample_type" in rk:
        _set_sample_type(root, "Rankings", _as_num(rk["sample_type"]), changes)
    if "sample_type" in ge:
        _set_sample_type(root, "BuildMode", _as_num(ge["sample_type"]), changes)

    # --- Datos: período completo y partición IS/OOS ---
    dt = profile.get("data") or {}
    if "date_from" in dt or "date_to" in dt:
        _set_data_dates(root, dt.get("date_from"), dt.get("date_to"), changes)
    if dt.get("out_of_sample"):
        _rewrite_out_of_sample(root, dt["out_of_sample"], changes)

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
            # `set_<categoria>`: lista EXACTA — activa las indicadas y desactiva el resto.
            # Es lo que permite aislar un edge: con el catálogo reducido a sus bloques,
            # el generador no puede combinar señales ajenas.
            set_key = f"set_{cat}"
            if set_key in bl:
                wanted = set(bl[set_key])
                _set_block_use(root, cat, wanted, True, changes, strict=strict)
                for el in _iter_cfx_blocks(root, cat):
                    if el.get("key") not in wanted and el.get("use") == "true":
                        el.set("use", "false")
                        changes.append({"setting": f"blocks.{el.get('key')}",
                                        "status": "changed", "from": "true", "to": "false"})
        if "fixed_params" in bl:
            pending = dict(bl["fixed_params"])
            for cat in BLOCK_CATEGORIES:
                spec = {k: v for k, v in pending.items()
                        if any(e.get("key") == k for e in _iter_cfx_blocks(root, cat))}
                if spec:
                    _set_block_fixed_params(root, cat, spec, changes, strict=strict)
                    for k in spec:
                        pending.pop(k, None)
            # Un bloque que no existe en NINGUNA categoría se filtraría en silencio
            # y el perfil parecería aplicado: abortamos para que el error se vea.
            if pending and strict:
                raise ValueError(
                    f"Bloques desconocidos en 'fixed_params': {sorted(pending)}")

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
                     "drawdown_pct_max", "rsquared_min", "sample_type",
                     "sqn_score_min", "sqn_min"},
        "genetic": set(GENETIC_KEYS) | {"sample_type"},
        "data": {"date_from", "date_to", "out_of_sample"},
        "exits": {"exit_after_bars_probability", "move_sl2be_probability",
                  "profit_target_probability", "stop_loss_probability",
                  "trailing_stop_probability"},
    }
    # Claves válidas dentro de la sección 'blocks'
    known_block_keys = {
        f"{pre}_{cat}"
        for pre in ("add", "remove", "set")
        for cat in BLOCK_CATEGORIES
    } | {"fixed_params"}
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
                 "chart_not_found", "block_not_found", "not_found", "conditions_not_found",
                 "invalid_range", "condition_not_found", "cloned_needs_check")]
    warnings += [f"ajuste desconocido ignorado: {u}" for u in unknown]

    return {
        "output": str(out),
        "applied": applied,
        "changes": changes,
        "warnings": warnings,
    }
