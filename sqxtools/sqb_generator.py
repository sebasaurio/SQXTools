"""SQB Generator — genera archivos .sqb optimizados para StrategyQuant."""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .models import SqbFile, SqbBlock


def generate_sqb(
    blocks_config: dict[str, list[dict]],
    output_path: str | Path,
    block_type: str = "simple",
    version: str = "144.2938",
) -> Path:
    """Genera un archivo .sqb con la configuración optimizada.
    
    Args:
        blocks_config: Diccionario con listas de bloques por categoría.
            {
                "signals": [{"key": "RSIFalling", "params": {"#Period#": "14"}}],
                "indicators": [{"key": "Indicators.RSI", "params": {"#Period#": "14"}}],
                "stopLimitBlocks": [{"key": "Stop/Limit Price Levels.ATR", "params": {"#Period#": "14"}}],
            }
        output_path: Ruta de salida del .sqb
        block_type: Tipo de estrategia
        version: Versión de StrategyQuant
    
    Returns:
        Path al archivo .sqb generado
    """
    root = ET.Element("Blocks")
    root.set("type", block_type)
    root.set("version", version)
    
    # Calibration
    calibration = ET.SubElement(root, "Calibration")
    calibration.set("useMaxSteps", "true")
    calibration.set("maxSteps", "50")
    calibration.set("calibrateBeforeStart", "false")
    
    # BuildingBlocks
    building_blocks = ET.SubElement(root, "BuildingBlocks")
    
    for category, blocks in blocks_config.items():
        for block_info in blocks:
            block_el = ET.SubElement(building_blocks, "Block")
            block_el.set("key", block_info["key"])
            block_el.set("weight", block_info.get("weight", "1"))
            block_el.set("use", block_info.get("use", "true"))
            block_el.set("category", category)
            
            if block_info.get("indicator_min"):
                block_el.set("indicatorMin", block_info["indicator_min"])
            if block_info.get("indicator_max"):
                block_el.set("indicatorMax", block_info["indicator_max"])
            
            # Generated
            generated = ET.SubElement(block_el, "Generated")
            generated.set("weight", block_info.get("weight", "1"))
            
            for param_key, param_value in block_info.get("params", {}).items():
                param_el = ET.SubElement(generated, "Param")
                param_el.set("key", param_key)
                param_el.set("name", param_key.replace("#", ""))
                param_el.set("type", _guess_param_type(param_value))
                param_el.set("paramType", "null")
                param_el.text = str(param_value)
            
            # Predefined
            predefined = ET.SubElement(block_el, "Predefined")
            predefined.set("changed", "false")
            
            # OrderTypes
            order_types = ET.SubElement(root, "OrderTypes")
            for ot in [
                {"key": "EnterAtMarket", "use": "false"},
                {"key": "EnterReverseAtMarket", "use": "false"},
                {"key": "EnterAtStop", "use": "true"},
                {"key": "EnterAtLimit", "use": "true"},
            ]:
                ot_el = ET.SubElement(order_types, "Block")
                ot_el.set("key", ot["key"])
                ot_el.set("weight", "1")
                ot_el.set("use", ot["use"])
                ot_el.set("category", "orderTypes")
            
            # ExitTypes
            exit_types = ET.SubElement(root, "ExitTypes")
            for et in [
                {"key": "ExitAfterBars.ExitAfterBars", "use": "true", "probability": "50"},
                {"key": "MoveSL2BE.MoveSL2BE", "use": "true", "probability": "100"},
                {"key": "MoveSL2BE.SL2BEAddPips", "use": "false", "probability": "50"},
                {"key": "ProfitTarget.ProfitTarget", "use": "true", "probability": "100"},
                {"key": "StopLoss.StopLoss", "use": "true", "probability": "100"},
                {"key": "TrailingStop.TrailingStop", "use": "true", "probability": "100"},
                {"key": "TrailingStop.TrailingActivation", "use": "false", "probability": "50"},
                {"key": "_ExitRule_", "use": "false", "probability": "50"},
            ]:
                et_el = ET.SubElement(exit_types, "Block")
                et_el.set("key", et["key"])
                et_el.set("weight", "1")
                et_el.set("use", et["use"])
                et_el.set("probability", et["probability"])
                et_el.set("category", "exitTypes")
            
            # CustomData
            custom_data = ET.SubElement(root, "CustomData")
            custom_data.set("showAll", "false")
    
    # Guardar como .sqb (ZIP con config.xml)
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    tree = ET.ElementTree(root)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("config.xml", "w") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)
    
    return out_path


def _guess_param_type(value: str) -> str:
    """Adivina el tipo de parámetro."""
    try:
        int(value)
        return "int"
    except ValueError:
        try:
            float(value)
            return "double"
        except ValueError:
            return "string"


def generate_optimized_sqb(
    edge_analysis: dict,
    output_path: str | Path,
) -> Path:
    """Genera un .sqb optimizado basado en el análisis de mercado."""
    blocks_config = {
        "signals": [],
        "indicators": [],
        "stopLimitBlocks": [],
    }
    
    # Signals desde edge_analyzer
    for sig in edge_analysis.get("indicators", {}).get("signals", []):
        blocks_config["signals"].append({
            "key": sig["name"],
            "weight": "1",
            "use": "true",
            "params": _get_default_params(sig["name"]),
        })
    
    # Indicators desde edge_analyzer
    for ind in edge_analysis.get("indicators", {}).get("indicators", []):
        blocks_config["indicators"].append({
            "key": ind["name"],
            "weight": "1",
            "use": "true",
            "params": _get_default_params(ind["name"]),
        })
    
    # Stop/Limit Blocks desde edge_analyzer
    for slb in edge_analysis.get("indicators", {}).get("stopLimitBlocks", []):
        blocks_config["stopLimitBlocks"].append({
            "key": slb["name"],
            "weight": "1",
            "use": "true",
            "params": _get_default_params(slb["name"]),
        })
    
    return generate_sqb(blocks_config, output_path)


# Parámetros por defecto para cada tipo de bloque
DEFAULT_PARAMS = {
    "SuperTrendDownTrend": {"#Chart#": "Main", "#Period#": "10", "#Multiplier#": "3"},
    "IsDowntrend": {"#Chart#": "Main", "#Period#": "20"},
    "RSIFalling": {"#Chart#": "Main", "#Period#": "14", "#Level#": "50"},
    "MACDSignalFalling": {"#Chart#": "Main", "#Fast#": "12", "#Slow#": "26", "#Signal#": "9"},
    "MACDMainFalling": {"#Chart#": "Main", "#Fast#": "12", "#Slow#": "26"},
    "ADXHigher": {"#Chart#": "Main", "#Period#": "14", "#Level#": "25"},
    "ATRRising": {"#Chart#": "Main", "#Period#": "14"},
    "BollingerBandsOutside": {"#Chart#": "Main", "#Period#": "20", "#Deviation#": "2"},
    "Indicators.RSI": {"#Chart#": "Main", "#Period#": "14"},
    "Indicators.MACD": {"#Chart#": "Main", "#Fast#": "12", "#Slow#": "26", "#Signal#": "9"},
    "Indicators.ATR": {"#Chart#": "Main", "#Period#": "14"},
    "Indicators.ADX": {"#Chart#": "Main", "#Period#": "14"},
    "Indicators.SuperTrend": {"#Chart#": "Main", "#Period#": "10", "#Multiplier#": "3"},
    "Stop/Limit Price Levels.RSI": {"#Chart#": "Main", "#Period#": "14", "#Level#": "30"},
    "Stop/Limit Price Levels.ATR": {"#Chart#": "Main", "#Period#": "14"},
    "Stop/Limit Price Levels.SuperTrend": {"#Chart#": "Main", "#Period#": "10", "#Multiplier#": "3"},
    "Stop/Limit Price Ranges.ATR": {"#Chart#": "Main", "#Period#": "14"},
}


def _get_default_params(block_name: str) -> dict[str, str]:
    """Obtiene parámetros por defecto para un bloque."""
    for key, params in DEFAULT_PARAMS.items():
        if key in block_name or block_name in key:
            return params.copy()
    return {"#Chart#": "Main"}
