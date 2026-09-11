"""Parser de archivos .sqb (StrategyQuant Block Settings).

Estructura:
  <Blocks type="simple" version="144.2938">
    <Calibration useMaxSteps="true" maxSteps="50" calibrateBeforeStart="false"/>
    <BuildingBlocks>
      <Block key="RSIFalling" weight="1" use="true" category="signals">
        <Generated weight="1">
          <Param key="#Period#" name="Period" type="int"
                 generation="random" minValue="7" maxValue="50" step="1"/>
        </Generated>
        <Predefined changed="false">
          <Params name="Default set 1" weight="1">
            <Param key="#Period#" generation="fixed" defaultValue="14"/>
          </Params>
        </Predefined>
      </Block>
    </BuildingBlocks>
    <OrderTypes>...</OrderTypes>
    <ExitTypes>...</ExitTypes>
    <CustomData showAll="false"/>
  </Blocks>

Notas de implementación:
- Se limpian los namespaces XML por robustez (algunas builds agregan un prefijo).
- Los parámetros se guardan con TODOS sus atributos (generation, min/max/step,
  defaultValue, values) — no solo el valor de texto, que en .sqb siempre viene vacío.
"""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .models import SqbFile, SqbBlock, SqbParam, SqbPredefined

# Atributos que pueden aparecer en un <Param>
_PARAM_ATTRS = (
    "key",
    "name",
    "type",
    "paramType",
    "generation",
    "minValue",
    "maxValue",
    "step",
    "defaultValue",
    "values",
    "allCharts",
)


def _clean(tag: str) -> str:
    """Quita el namespace de un tag XML ({ns}Tag -> Tag)."""
    return tag.split("}")[-1] if "}" in tag else tag


def parse_sqb(path: str | Path) -> SqbFile:
    """Parsea un archivo .sqb (ZIP con config.xml)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el archivo: {p}")

    with zipfile.ZipFile(p) as z:
        if "config.xml" not in z.namelist():
            raise ValueError(f"El .sqb no contiene config.xml. Contenido: {z.namelist()}")
        with z.open("config.xml") as f:
            root = ET.parse(f).getroot()

    sqb = SqbFile(
        filename=p.name,
        block_type=root.get("type", "simple"),
        version=root.get("version", ""),
    )

    for child in root:
        tag = _clean(child.tag)
        if tag == "Calibration":
            sqb.calibration = {
                "useMaxSteps": child.get("useMaxSteps", "true"),
                "maxSteps": child.get("maxSteps", "50"),
                "calibrateBeforeStart": child.get("calibrateBeforeStart", "false"),
            }
        elif tag == "BuildingBlocks":
            sqb.building_blocks = _parse_block_list(child)
        elif tag == "OrderTypes":
            sqb.order_types = _parse_block_list(child)
        elif tag == "ExitTypes":
            sqb.exit_types = _parse_block_list(child)
        elif tag == "CustomData":
            sqb.custom_data = {"showAll": child.get("showAll", "false")}

    return sqb


def _parse_block_list(el: ET.Element) -> list[SqbBlock]:
    """Parsea una colección de <Block> (BuildingBlocks, OrderTypes, ExitTypes)."""
    blocks = []
    for block_el in el:
        if _clean(block_el.tag) != "Block":
            continue

        block = SqbBlock(
            key=block_el.get("key", ""),
            weight=block_el.get("weight", "1"),
            use=block_el.get("use", "false") == "true",
            category=block_el.get("category", ""),
            indicator_min=block_el.get("indicatorMin"),
            indicator_max=block_el.get("indicatorMax"),
            indicator_step=block_el.get("indicatorStep"),
        )

        for sub in block_el:
            sub_tag = _clean(sub.tag)
            if sub_tag == "Generated":
                block.generated = SqbParam(
                    weight=sub.get("weight", "1"),
                    params=_parse_params(sub),
                )
            elif sub_tag == "Predefined":
                block.predefined = SqbPredefined(
                    changed=sub.get("changed", "false") == "true",
                    sets=_parse_predefined_sets(sub),
                )

        blocks.append(block)
    return blocks


def _parse_params(el: ET.Element) -> list[dict]:
    """Parsea elementos <Param> conservando todos sus atributos."""
    params = []
    for param_el in el:
        if _clean(param_el.tag) != "Param":
            continue
        param: dict[str, Any] = {}
        for attr in _PARAM_ATTRS:
            val = param_el.get(attr)
            if val is not None:
                param[attr] = val
        # Texto del elemento (en .sqb suele venir vacío, pero puede traer valores)
        text = (param_el.text or "").strip()
        if text:
            param["value"] = text
        params.append(param)
    return params


def _parse_predefined_sets(el: ET.Element) -> list[dict]:
    """Parsea los <Params> dentro de <Predefined>, incluyendo sus parámetros."""
    sets = []
    for params_el in el:
        if _clean(params_el.tag) != "Params":
            continue
        sets.append({
            "name": params_el.get("name", ""),
            "weight": params_el.get("weight", "1"),
            "params": _parse_params(params_el),
        })
    return sets


def get_block_summary(sqb: SqbFile) -> dict[str, Any]:
    """Resumen del archivo .sqb organizado por categoría."""
    summary: dict[str, Any] = {
        "filename": sqb.filename,
        "type": sqb.block_type,
        "version": sqb.version,
        "total_blocks": len(sqb.building_blocks),
        "active_blocks": sum(1 for b in sqb.building_blocks if b.use),
        "by_category": {},
        "active_by_category": {},
        "order_types": [],
        "exit_types": [],
    }

    for block in sqb.building_blocks:
        cat = block.category or "uncategorized"
        summary["by_category"].setdefault(cat, [])
        summary["active_by_category"].setdefault(cat, [])

        block_info = _block_to_info(block)
        summary["by_category"][cat].append(block_info)
        if block.use:
            summary["active_by_category"][cat].append(block_info)

    for block in sqb.order_types:
        summary["order_types"].append({"key": block.key, "use": block.use})

    for block in sqb.exit_types:
        summary["exit_types"].append({"key": block.key, "use": block.use})

    return summary


def _block_to_info(block: SqbBlock) -> dict[str, Any]:
    """Extrae la info relevante de un bloque (params con valor efectivo)."""
    info: dict[str, Any] = {
        "key": block.key,
        "use": block.use,
        "weight": block.weight,
    }
    if block.indicator_min is not None:
        info["indicatorMin"] = block.indicator_min
        info["indicatorMax"] = block.indicator_max
        info["indicatorStep"] = block.indicator_step

    if block.generated and block.generated.params:
        info["params"] = _effective_params(block.generated.params)

    if block.predefined and block.predefined.sets:
        info["predefined_sets"] = len(block.predefined.sets)

    return info


def _effective_params(params: list[dict]) -> dict[str, Any]:
    """Devuelve el valor efectivo de cada parámetro: defaultValue > values > min-max."""
    out: dict[str, Any] = {}
    for p in params:
        key = p.get("key", "")
        if p.get("defaultValue") is not None:
            out[key] = p["defaultValue"]
        elif p.get("values"):
            out[key] = p["values"]
        elif p.get("minValue") is not None and p["minValue"] not in (
            "-1000001", "-1000002", "-1000003", "-1000004", "null"
        ):
            out[key] = f"{p['minValue']}..{p.get('maxValue', '?')}"
    return out
