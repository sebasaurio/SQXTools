"""Parser de archivos .sqb (StrategyQuant Block Settings).

Estructura:
  <Blocks type="simple" version="144.2938">
    <Calibration .../>
    <BuildingBlocks>
      <Block key="..." weight="1" use="true" category="signals">
        <Generated weight="1">
          <Param key="#Chart#" name="Chart" type="data" paramType="null"/>
          <Param key="#Period#" name="Period" type="int" paramType="null">14</Param>
        </Generated>
        <Predefined changed="false">
          <Params name="Default set 1" weight="1"/>
        </Predefined>
      </Block>
    </BuildingBlocks>
    <OrderTypes>...</OrderTypes>
    <ExitTypes>...</ExitTypes>
    <CustomData showAll="false"/>
  </Blocks>
"""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .models import SqbFile, SqbBlock, SqbParam, SqbPredefined


def parse_sqb(path: str | Path) -> SqbFile:
    """Parsea un archivo .sqb (ZIP con config.xml)."""
    p = Path(path)
    with zipfile.ZipFile(p) as z:
        if "config.xml" not in z.namelist():
            raise ValueError(f"El .sqb no contiene config.xml. Contenido: {z.namelist()}")
        with z.open("config.xml") as f:
            tree = ET.parse(f)
    
    root = tree.getroot()
    sqb = SqbFile(
        filename=p.name,
        block_type=root.get("type", "simple"),
        version=root.get("version", ""),
    )
    
    for child in root:
        tag = child.tag
        if tag == "Calibration":
            sqb.calibration = {
                "useMaxSteps": child.get("useMaxSteps", "true"),
                "maxSteps": child.get("maxSteps", "50"),
                "calibrateBeforeStart": child.get("calibrateBeforeStart", "false"),
            }
        elif tag == "BuildingBlocks":
            sqb.building_blocks = _parse_building_blocks(child)
        elif tag == "OrderTypes":
            sqb.order_types = _parse_block_list(child)
        elif tag == "ExitTypes":
            sqb.exit_types = _parse_block_list(child)
        elif tag == "CustomData":
            sqb.custom_data = {"showAll": child.get("showAll", "false")}
    
    return sqb


def _parse_building_blocks(el: ET.Element) -> list[SqbBlock]:
    """Parsea los BuildingBlocks."""
    blocks = []
    for block_el in el:
        if block_el.tag == "Block":
            block = SqbBlock(
                key=block_el.get("key", ""),
                weight=block_el.get("weight", "1"),
                use=block_el.get("use", "false") == "true",
                category=block_el.get("category", ""),
                indicator_min=block_el.get("indicatorMin"),
                indicator_max=block_el.get("indicatorMax"),
            )
            
            for sub in block_el:
                if sub.tag == "Generated":
                    block.generated = SqbParam(
                        weight=sub.get("weight", "1"),
                        params=_parse_params(sub),
                    )
                elif sub.tag == "Predefined":
                    block.predefined = SqbPredefined(
                        changed=sub.get("changed", "false") == "true",
                        sets=_parse_predefined_sets(sub),
                    )
            
            blocks.append(block)
    return blocks


def _parse_block_list(el: ET.Element) -> list[SqbBlock]:
    """Parsea OrderTypes o ExitTypes."""
    blocks = []
    for block_el in el:
        if block_el.tag == "Block":
            block = SqbBlock(
                key=block_el.get("key", ""),
                weight=block_el.get("weight", "1"),
                use=block_el.get("use", "false") == "true",
                category=block_el.get("category", ""),
            )
            
            for sub in block_el:
                if sub.tag == "Generated":
                    block.generated = SqbParam(
                        weight=sub.get("weight", "1"),
                        params=_parse_params(sub),
                    )
                elif sub.tag == "Predefined":
                    block.predefined = SqbPredefined(
                        changed=sub.get("changed", "false") == "true",
                        sets=_parse_predefined_sets(sub),
                    )
            
            blocks.append(block)
    return blocks


def _parse_params(el: ET.Element) -> list[dict]:
    """Parsea elementos Param."""
    params = []
    for param_el in el:
        if param_el.tag == "Param":
            params.append({
                "key": param_el.get("key", ""),
                "name": param_el.get("name", ""),
                "type": param_el.get("type", "string"),
                "paramType": param_el.get("paramType", "null"),
                "value": param_el.text or "",
            })
    return params


def _parse_predefined_sets(el: ET.Element) -> list[dict]:
    """Parsea Params dentro de Predefined."""
    sets = []
    for params_el in el:
        if params_el.tag == "Params":
            sets.append({
                "name": params_el.get("name", ""),
                "weight": params_el.get("weight", "1"),
            })
    return sets


def get_block_summary(sqb: SqbFile) -> dict[str, Any]:
    """Resumen del archivo .sqb organizado por categoría."""
    summary = {
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
        if cat not in summary["by_category"]:
            summary["by_category"][cat] = []
            summary["active_by_category"][cat] = []
        
        block_info = {
            "key": block.key,
            "use": block.use,
            "weight": block.weight,
        }
        if block.generated and block.generated.params:
            block_info["params"] = {p["key"]: p["value"] for p in block.generated.params if p["value"]}
        
        summary["by_category"][cat].append(block_info)
        if block.use:
            summary["active_by_category"][cat].append(block_info)
    
    for block in sqb.order_types:
        summary["order_types"].append({
            "key": block.key,
            "use": block.use,
        })
    
    for block in sqb.exit_types:
        summary["exit_types"].append({
            "key": block.key,
            "use": block.use,
        })
    
    return summary
