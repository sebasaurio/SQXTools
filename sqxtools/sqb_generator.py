"""SQB Generator — genera archivos .sqb optimizados para StrategyQuant.

Estructura correcta (aprendida del archivo original):
- Indicators: indicatorMin/Max/Step en Block, NO llevan Predefined sets
- Signals/Stops: SÍ llevan Predefined sets (16 sets)
- Valores random sin constraint: -1000003/-1000004 (períodos), -1000001/-1000002 (shift), null (chart)
- Predefined: min/max/step = 'undefined' para usar rango por defecto
"""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def generate_sqb(
    blocks_config: dict[str, list[dict]],
    output_path: str | Path,
    block_type: str = "simple",
    version: str = "144.2938",
) -> Path:
    root = ET.Element("Blocks")
    root.set("type", block_type)
    root.set("version", version)
    
    # Calibration
    cal = ET.SubElement(root, "Calibration")
    cal.set("useMaxSteps", "true")
    cal.set("maxSteps", "50")
    cal.set("calibrateBeforeStart", "false")
    
    # BuildingBlocks
    bb = ET.SubElement(root, "BuildingBlocks")
    
    for category, blocks in blocks_config.items():
        for block_info in blocks:
            block_el = ET.SubElement(bb, "Block")
            block_el.set("key", block_info["key"])
            block_el.set("weight", block_info.get("weight", "1"))
            block_el.set("use", block_info.get("use", "true"))
            block_el.set("category", category)
            
            # Indicators: indicatorMin/Max/Step en el Block
            if category == "indicators":
                block_el.set("indicatorMin", block_info.get("indicatorMin", "0"))
                block_el.set("indicatorMax", block_info.get("indicatorMax", "100"))
                block_el.set("indicatorStep", block_info.get("indicatorStep", "0.5"))
            
            # Generated
            gen = ET.SubElement(block_el, "Generated")
            gen.set("weight", block_info.get("weight", "1"))
            
            for pkey, pval in block_info.get("params", {}).items():
                p = ET.SubElement(gen, "Param")
                p.set("key", pkey)
                p.set("name", pkey.replace("#", ""))
                p.set("paramType", "null")
                
                if isinstance(pval, dict):
                    p.set("type", pval.get("type", "int"))
                    p.set("generation", pval.get("generation", "random"))
                    if pval.get("generation") == "fixed":
                        p.set("defaultValue", str(pval.get("default", "")))
                    else:
                        p.set("minValue", str(pval.get("min", "-1000003")))
                        p.set("maxValue", str(pval.get("max", "-1000004")))
                        p.set("step", str(pval.get("step", "1")))
                    if pval.get("values"):
                        p.set("values", str(pval["values"]))
                    if pval.get("allCharts"):
                        p.set("allCharts", "true")
                else:
                    p.set("type", "string" if isinstance(pval, str) and not pval.isdigit() else "int")
                    p.set("generation", "random")
                    p.set("minValue", "-1000003")
                    p.set("maxValue", "-1000004")
                    p.set("step", "1")
            
            # Predefined
            pred = ET.SubElement(block_el, "Predefined")
            pred.set("changed", "false")
            
            # Indicators NO llevan Predefined sets
            if category != "indicators":
                num_sets = block_info.get("num_sets", 16)
                for i in range(1, num_sets + 1):
                    ps = ET.SubElement(pred, "Params")
                    ps.set("name", f"Default set {i}")
                    ps.set("weight", "1")
                    
                    for pkey, pval in block_info.get("params", {}).items():
                        p = ET.SubElement(ps, "Param")
                        p.set("key", pkey)
                        p.set("name", pkey.replace("#", ""))
                        
                        if isinstance(pval, dict):
                            p.set("type", pval.get("type", "int"))
                            if i % 2 == 1:  # Sets impares: fixed
                                p.set("generation", "fixed")
                                p.set("defaultValue", str(pval.get("default", pval.get("min", 0))))
                            else:  # Sets pares: random
                                p.set("generation", "random")
                                p.set("minValue", "undefined")
                                p.set("maxValue", "undefined")
                                p.set("step", "undefined")
                        else:
                            p.set("type", "string")
                            p.set("generation", "random")
    
    # OrderTypes
    ot = ET.SubElement(root, "OrderTypes")
    for item in [
        {"key": "EnterAtMarket", "use": "false"},
        {"key": "EnterReverseAtMarket", "use": "false"},
        {"key": "EnterAtStop", "use": "true"},
        {"key": "EnterAtLimit", "use": "true"},
    ]:
        el = ET.SubElement(ot, "Block")
        el.set("key", item["key"])
        el.set("weight", "1")
        el.set("use", item["use"])
        el.set("category", "orderTypes")
    
    # ExitTypes
    et = ET.SubElement(root, "ExitTypes")
    for item in [
        {"key": "ExitAfterBars.ExitAfterBars", "use": "true", "probability": "50"},
        {"key": "MoveSL2BE.MoveSL2BE", "use": "true", "probability": "100"},
        {"key": "MoveSL2BE.SL2BEAddPips", "use": "false", "probability": "50"},
        {"key": "ProfitTarget.ProfitTarget", "use": "true", "probability": "100"},
        {"key": "StopLoss.StopLoss", "use": "true", "probability": "100"},
        {"key": "TrailingStop.TrailingStop", "use": "true", "probability": "100"},
        {"key": "TrailingStop.TrailingActivation", "use": "false", "probability": "50"},
        {"key": "_ExitRule_", "use": "false", "probability": "50"},
    ]:
        el = ET.SubElement(et, "Block")
        el.set("key", item["key"])
        el.set("weight", "1")
        el.set("use", item["use"])
        el.set("probability", item["probability"])
        el.set("category", "exitTypes")
    
    # CustomData
    cd = ET.SubElement(root, "CustomData")
    cd.set("showAll", "false")
    
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    tree = ET.ElementTree(root)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("config.xml", "w") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)
    
    return out_path


def generate_optimized_sqb(edge_analysis, output_path):
    blocks_config = {
        "signals": [],
        "indicators": [],
        "stopLimitBlocks": [],
    }
    
    for sig in edge_analysis.get("indicators", {}).get("signals", []):
        blocks_config["signals"].append({
            "key": sig["name"],
            "weight": "1",
            "use": "true",
            "params": _get_params_for_block(sig["name"]),
        })
    
    for ind in edge_analysis.get("indicators", {}).get("indicators", []):
        blocks_config["indicators"].append({
            "key": ind["name"],
            "weight": "1",
            "use": "true",
            "indicatorMin": _get_indicator_min(ind["name"]),
            "indicatorMax": _get_indicator_max(ind["name"]),
            "indicatorStep": _get_indicator_step(ind["name"]),
            "params": _get_params_for_block(ind["name"]),
        })
    
    for slb in edge_analysis.get("indicators", {}).get("stopLimitBlocks", []):
        blocks_config["stopLimitBlocks"].append({
            "key": slb["name"],
            "weight": "1",
            "use": "true",
            "params": _get_params_for_block(slb["name"]),
        })
    
    return generate_sqb(blocks_config, output_path)


def _get_indicator_min(name: str) -> str:
    if "RSI" in name or "Stochastic" in name:
        return "0"
    elif "MACD" in name:
        return "-5"
    elif "ATR" in name:
        return "-5000"
    elif "ADX" in name:
        return "0"
    elif "CCI" in name:
        return "-200"
    return "0"


def _get_indicator_max(name: str) -> str:
    if "RSI" in name or "Stochastic" in name:
        return "100"
    elif "MACD" in name:
        return "5"
    elif "ATR" in name:
        return "5000"
    elif "ADX" in name:
        return "100"
    elif "CCI" in name:
        return "200"
    return "100"


def _get_indicator_step(name: str) -> str:
    if "RSI" in name or "Stochastic" in name:
        return "0.5"
    elif "MACD" in name:
        return "0.001"
    elif "ATR" in name:
        return "0.001"
    elif "ADX" in name:
        return "0.5"
    elif "CCI" in name:
        return "0.5"
    return "0.5"


def _get_params_for_block(block_name: str) -> dict:
    CATALOG = {
        "SuperTrendDownTrend": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Multiplier#": {"type": "double", "min": 1.0, "max": 5.0, "step": 0.5},
        },
        "IsDowntrend": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
        },
        "RSIFalling": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Level#": {"type": "double", "min": 20, "max": 80, "step": 10},
        },
        "MACDSignalFalling": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Fast#": {"type": "int", "min": 5, "max": 20, "step": 1},
            "#Slow#": {"type": "int", "min": 20, "max": 50, "step": 1},
            "#Signal#": {"type": "int", "min": 5, "max": 15, "step": 1},
        },
        "ADXHigher": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Level#": {"type": "double", "min": 10, "max": 50, "step": 5},
        },
        "ATRRising": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
        },
        "BollingerBandsOutside": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 10, "max": 50, "step": 1},
            "#Deviation#": {"type": "double", "min": 1.0, "max": 3.0, "step": 0.5},
        },
        "Indicators.RSI": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#ComputedFrom#": {"type": "int", "generation": "random", "values": "Close=0,Open=1,High=2,Low=3,Median=4,Typical=5,Weighted=6"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Shift#": {"type": "int", "min": -1000001, "max": -1000002, "step": 1},
        },
        "Indicators.MACD": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#ComputedFrom#": {"type": "int", "generation": "random", "values": "Close=0,Open=1,High=2,Low=3,Median=4,Typical=5,Weighted=6"},
            "#Fast#": {"type": "int", "min": 5, "max": 20, "step": 1},
            "#Slow#": {"type": "int", "min": 20, "max": 50, "step": 1},
            "#Smooth#": {"type": "int", "min": 5, "max": 15, "step": 1},
            "#Shift#": {"type": "int", "min": -1000001, "max": -1000002, "step": 1},
            "#Line#": {"type": "int", "generation": "random", "values": "Main=0,Signal=1"},
        },
        "Indicators.ATR": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Shift#": {"type": "int", "min": -1000001, "max": -1000002, "step": 1},
        },
        "Indicators.ADX": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Shift#": {"type": "int", "min": -1000001, "max": -1000002, "step": 1},
        },
        "Stop/Limit Price Levels.RSI": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Level#": {"type": "double", "min": 20, "max": 80, "step": 10},
        },
        "Stop/Limit Price Levels.ATR": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
        },
        "Stop/Limit Price Levels.SuperTrend": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
            "#Multiplier#": {"type": "double", "min": 1.0, "max": 5.0, "step": 0.5},
        },
        "Stop/Limit Price Ranges.ATR": {
            "#Chart#": {"type": "data", "generation": "random", "allCharts": "true"},
            "#Period#": {"type": "int", "min": 7, "max": 50, "step": 1},
        },
    }
    
    for key, params in CATALOG.items():
        if key in block_name or block_name in key:
            return params.copy()
    return {"#Period#": {"type": "int", "min": 7, "max": 50, "step": 1}}
