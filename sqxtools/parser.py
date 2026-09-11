"""Parser de archivos .cfx de StrategyQuant (ZIP con config.xml).

Estructura real:
  <Task type="Build" ...>
    <Settings>
      <Options/>
      <WhatToBuild/>
      <RiskMoneyManagement/>
      <Data/>
      <Rankings/>
      <PartsToImprove/>
      <CrossChecks/>
      <Notes/>
      <Blocks>            ← building config, la sección clave
        <Calibration/>
        <BuildingBlocks/> ← 524 bloques típicos
        <OrderTypes/>
        <ExitTypes/>
        <CustomData/>
      </Blocks>
      <ATMs/>
      <Databanks/>
      <Resources/>
    </Settings>
  </Task>
"""

import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .models import CfxConfig, CfxType


def _parse_value(raw: str | None) -> tuple[Any, str]:
    if raw is None:
        return "", "string"
    v = raw.strip().strip('"').strip("'")
    if v.lower() in ("true", "false"):
        return v.lower() == "true", "bool"
    if re.fullmatch(r"-?\d+", v):
        return int(v), "int"
    if re.fullmatch(r"-?\d+\.\d+", v):
        return float(v), "float"
    return v, "string"


def parse_cfx(path: str | Path) -> CfxConfig:
    """Parsea un archivo .cfx (ZIP con config.xml)."""
    p = Path(path)
    with zipfile.ZipFile(p) as z:
        if "config.xml" not in z.namelist():
            raise ValueError(f"El .cfx no contiene config.xml. Contenido: {z.namelist()}")
        with z.open("config.xml") as f:
            tree = ET.parse(f)

    root = tree.getroot()
    cfg = CfxConfig(
        filename=p.name,
        cfx_type=_infer_cfx_type(root),
        version=root.get("version", ""),
        metadata={k: v for k, v in root.attrib.items() if k not in ("type", "version")},
    )

    settings = root.find("Settings")
    if settings is None:
        return cfg

    for child in settings:
        tag = child.tag
        if tag == "Options":
            cfg.settings = _parse_options(child)
        elif tag == "WhatToBuild":
            cfg.what_to_build = _parse_what_to_build(child)
        elif tag == "RiskMoneyManagement":
            cfg.risk_money_management = _parse_risk_mm(child)
        elif tag == "Data":
            cfg.data = _parse_data(child)
        elif tag == "Rankings":
            cfg.rankings = _parse_rankings(child)
        elif tag == "PartsToImprove":
            cfg.parts_to_improve = _parse_parts_to_improve(child)
        elif tag == "CrossChecks":
            cfg.cross_checks = _parse_cross_checks(child)
        elif tag == "Notes":
            cfg.notes = _parse_notes(child)
        elif tag == "Blocks":
            cfg.blocks = _parse_blocks(child)
        elif tag == "ATMs":
            cfg.atms = _parse_atms(child)
        elif tag == "Databanks":
            cfg.databanks = _parse_databanks(child)
        elif tag == "Resources":
            cfg.resources = _parse_resources(child)
        else:
            cfg.raw_sections[tag] = _element_to_dict(child)

    return cfg


def _infer_cfx_type(root: ET.Element) -> CfxType:
    t = root.get("type", "").lower()
    return {
        "build": CfxType.BUILD,
        "retester": CfxType.RETESTER,
        "optimizer": CfxType.OPTIMIZER,
        "buildingconfig": CfxType.BUILDING_CONFIG,
        "customproject": CfxType.CUSTOM_PROJECT,
        "info": CfxType.INFO,
    }.get(t, CfxType.UNKNOWN)


def _parse_options(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"customSettings": el.get("customSettings", "false")}
    for child in el:
        if child.tag == "BuildTradingOptions":
            params = []
            for params_container in child:
                if params_container.tag == "Params":
                    for p in params_container:
                        if p.tag in ("Param", "Parameter"):
                            key = p.get("key", "")
                            name = p.get("name", key)
                            value, typ = _parse_value(p.text)
                            params.append({"key": key, "name": name, "value": value, "type": typ, "className": p.get("className", "")})
            result["trading_options"] = params
    return result


def _parse_what_to_build(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in el:
        tag = child.tag
        if tag == "StrategyType":
            result["strategy_type"] = {k: child.get(k, "") for k in ("type", "additionalCharts", "templateFile", "improveType", "strategyFile")}
        elif tag == "RulesComplexity":
            charts = [{"name": c.get("name", ""), "minConditions": c.get("minConditions", ""), "maxConditions": c.get("maxConditions", ""), "minExitConditions": c.get("minExitConditions", "")} for c in child if c.tag == "Chart"]
            result["rules_complexity"] = {"useDifferentSettings": child.get("useDifferentSettings", "false"), "charts": charts}
        elif tag == "MarketSides":
            sides: dict[str, Any] = {"type": child.get("type", "")}
            for sub in child:
                if sub.tag in ("EntrySymmetry", "ExitSymmetry"):
                    sides[sub.tag.lower()] = (sub.text or "").strip()
            result["market_sides"] = sides
        elif tag == "SLPTOptions":
            result["slpt_options"] = _parse_slpt_options(child)
        elif tag == "BuildMode":
            result["build_mode"] = _parse_build_mode(child)
    return result


def _parse_slpt_options(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in el:
        tag = child.tag
        if tag in {"SLRequired", "SLFixedPips", "PTRequired", "PTFixedPips", "SeparatedSettings", "SLATR", "PTATR", "LimitSLPTRRR", "SLIndicatorBased", "PTIndicatorBased", "SLPercent", "PTPercent"}:
            result[tag] = (child.text or "").strip() == "true"
        else:
            result[tag] = (child.text or "").strip()
    return result


def _parse_build_mode(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"generationType": el.get("generationType", "")}
    for child in el:
        tag = child.tag
        if tag in {"PopulationSize", "MaxGenerations", "CrossoverProbability", "MutationProbability", "Islands", "MigrationModulo", "MigrationRate", "InitGenerationType", "DecimationCoef", "FreshBloodWeakestPct", "FreshBloodWeakestGenerations"}:
            result[tag] = (child.text or "").strip()
        elif tag in {"ShowAdvancedGeneticSettings", "ShowLastGenerationDatabank", "FreshBloodReplaceSimilar", "FreshBloodReplaceWeakest"}:
            result[tag] = (child.text or "").strip() == "true"
        elif tag == "Conditions":
            result["conditions"] = _parse_conditions(child)
        elif tag == "EvoRestartOnFinish":
            result["evo_restart_on_finish"] = (child.text or "").strip() == "true"
        elif tag == "EvoRestartOnStagnation":
            result["evo_restart_on_stagnation"] = {"status": child.get("status", ""), "fitnessType": child.get("fitnessType", ""), "generations": child.get("generations", "")}
        elif tag == "EvoInSamplePeriod":
            result["evo_in_sample_period"] = child.get("ratio", "")
    return result


def _parse_conditions(el: ET.Element) -> list[dict[str, Any]]:
    result = []
    for child in el:
        if child.tag == "Condition":
            cond: dict[str, Any] = {"use": child.get("use", "false") == "true"}
            for sub in child:
                tag = sub.tag
                if tag == "Left-Side":
                    cond["left_side"] = _parse_side(sub)
                elif tag == "Comparator":
                    cond["comparator"] = sub.get("value", "")
                elif tag == "Right-Side":
                    cond["right_side"] = _parse_side(sub)
            result.append(cond)
    return result


def _parse_side(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"valueType": el.get("valueType", "")}
    for child in el:
        tag = child.tag
        if tag == "Column-Value":
            result["column"] = {k: child.get(k, "") for k in child.attrib}
        elif tag == "Numeric-Value":
            result["numeric"] = child.get("value", "")
        else:
            result[tag] = {k: child.get(k, "") for k in child.attrib}
    return result


def _parse_risk_mm(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"customSettings": el.get("customSettings", "false")}
    for child in el:
        tag = child.tag
        if tag == "MoneyManagement":
            methods = []
            for method in child:
                if method.tag == "Method":
                    m: dict[str, Any] = {"type": method.get("type", ""), "use": method.get("use", "false") == "true", "params": []}
                    for sub in method:
                        if sub.tag == "Params":
                            for p in sub:
                                if p.tag in ("Param", "Parameter"):
                                    key = p.get("key", "")
                                    name = p.get("name", key)
                                    value, typ = _parse_value(p.text)
                                    m["params"].append({"key": key, "name": name, "value": value, "type": typ})
                        elif sub.tag == "Parameter":
                            key = sub.get("key", "")
                            name = sub.get("name", key)
                            value, typ = _parse_value(sub.text)
                            m["params"].append({"key": key, "name": name, "value": value, "type": typ})
                    methods.append(m)
                elif method.tag == "InitialCapital":
                    result["initial_capital"] = (method.text or "").strip()
            result["methods"] = methods
        elif tag == "RiskManagement":
            rm: dict[str, Any] = {"maxDrawdown": child.get("maxDrawdown", "")}
            for sub in child:
                if sub.tag == "Method":
                    rm["method"] = {"type": sub.get("type", ""), "use": sub.get("use", "false") == "true"}
            result["risk_management"] = rm
    return result


def _parse_data(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in el:
        tag = child.tag
        if tag == "Setups":
            setups = []
            for setup in child:
                if setup.tag == "Setup":
                    s: dict[str, Any] = {
                        "dateFrom": setup.get("dateFrom", ""), "dateTo": setup.get("dateTo", ""),
                        "testPrecision": setup.get("testPrecision", ""), "session": setup.get("session", ""),
                        "charts": [], "commissions": {}, "swap": {},
                    }
                    for sub in setup:
                        if sub.tag == "Chart":
                            s["charts"].append({"symbol": sub.get("symbol", ""), "timeframe": sub.get("timeframe", ""), "spread": sub.get("spread", "")})
                        elif sub.tag == "Commissions":
                            for method in sub:
                                if method.tag == "Method":
                                    s["commissions"] = {"type": method.get("type", ""), "use": method.get("use", "false") == "true"}
                        elif sub.tag == "Swap":
                            s["swap"] = {"use": sub.get("use", "false") == "true", "type": sub.get("type", ""), "long": sub.get("long", ""), "short": sub.get("short", "")}
                    setups.append(s)
            result["setups"] = setups
        elif tag == "OutOfSample":
            ranges = [{"dateFrom": r.get("dateFrom", ""), "dateTo": r.get("dateTo", ""), "type": r.get("type", "")} for r in child if r.tag == "Range"]
            result["out_of_sample"] = {"showGraph": child.get("showGraph", "true"), "ranges": ranges}
    return result


def _parse_rankings(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"type": el.get("type", "")}
    for child in el:
        tag = child.tag
        if tag == "MaxStrategies":
            result["max_strategies"] = (child.text or "").strip()
        elif tag == "FitnessCriteria":
            fc: dict[str, Any] = {"method": child.get("method", ""), "useFitnessByIndex": child.get("useFitnessByIndex", "false")}
            for sub in child:
                if sub.tag == "Settings":
                    for ranking in sub:
                        if ranking.tag == "Ranking":
                            fc["type"] = ranking.get("type", "")
            result["fitness_criteria"] = fc
        elif tag == "ConditionsType":
            result["conditions_type"] = (child.text or "").strip()
        elif tag == "Conditions":
            result["conditions"] = _parse_conditions(child)
        elif tag == "DismissTooSimilarStrategies":
            result["dismiss_too_similar"] = (child.text or "").strip() == "true"
        elif tag == "AutomaticDismissal":
            problems = [{"code": p.get("code", ""), "dismiss": p.get("dismiss", "")} for p in child if p.tag == "Problem"]
            result["automatic_dismissal"] = {"warnings": child.get("warnings", "false"), "problems": problems}
        elif tag == "StopCondition":
            result["stop_condition"] = {"type": child.get("type", ""), "passedStrategies": child.get("passedStrategies", ""), "restartCount": child.get("restartCount", ""), "days": child.get("days", "")}
        elif tag == "FitPortfolio":
            fp: dict[str, Any] = {"active": child.get("active", "false") == "true", "databank": child.get("databank", "")}
            for sub in child:
                if sub.tag == "Correlation":
                    fp["correlation"] = {"max": sub.get("max", ""), "type": sub.get("type", ""), "period": sub.get("period", ""), "allowNegative": sub.get("allowNegative", "")}
            result["fit_portfolio"] = fp
        elif tag == "CustomAnalysis":
            result["custom_analysis"] = {"method": child.get("method", ""), "filter": child.get("filter", "false") == "true", "inputArgs": child.get("inputArgs", "")}
    return result


def _parse_parts_to_improve(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"improveATM": el.get("improveATM", "false") == "true"}
    for child in el:
        tag = child.tag
        if tag in ("EntryRules", "OrderTypes", "ExitRules"):
            section: dict[str, Any] = {"symmetry": child.get("symmetry", "false")}
            for sub in child:
                if sub.tag in ("LongImprovement", "ShortImprovement"):
                    section[sub.tag] = {"use": sub.get("use", "false") == "true", "action": sub.get("action", "")}
            result[tag] = section
    return result


def _parse_cross_checks(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"use": el.get("use", "false") == "true", "evaluateAll": el.get("evaluateAll", "false") == "true"}
    check_tags = {"RetestOnAdditionalMarkets", "WalkForwardOptimization", "RetestWithHigherPrecision", "MonteCarloRetest", "WalkForwardMatrix", "MonteCarloManipulation", "OptProfileSysParamPermutation", "WhatIf", "SequentialOptimization"}
    for child in el:
        tag = child.tag
        if tag in check_tags:
            cc: dict[str, Any] = {"use": child.get("use", "false") == "true"}
            for sub in child:
                if sub.tag == "Settings":
                    cc["settings"] = _element_to_dict(sub)
                elif sub.tag == "AcceptanceSettings":
                    cc["acceptance"] = _element_to_dict(sub)
            result[tag] = cc
    return result


def _parse_notes(el: ET.Element) -> str:
    return (el.text or "").strip()


def _parse_blocks(el: ET.Element) -> dict[str, Any]:
    """Parsea la sección Blocks — el corazón del building config."""
    result: dict[str, Any] = {}
    for child in el:
        tag = child.tag
        if tag == "Calibration":
            result["calibration"] = (child.text or "").strip()
        elif tag == "BuildingBlocks":
            blocks = []
            for block in child:
                if block.tag == "Block":
                    b: dict[str, Any] = {
                        "key": block.get("key", ""),
                        "weight": block.get("weight", "1"),
                        "use": block.get("use", "false") == "true",
                        "category": block.get("category", ""),
                        "params": [],
                        "formulas": [],
                        "values": [],
                        "predefined_changed": False,
                    }
                    for sub in block:
                        if sub.tag == "Generated":
                            for param in sub:
                                if param.tag == "Param":
                                    key = param.get("key", "")
                                    name = param.get("name", key)
                                    value, typ = _parse_value(param.text)
                                    b["params"].append({"key": key, "name": name, "value": value, "type": typ, "paramType": param.get("paramType", "")})
                        elif sub.tag == "Formulas":
                            for formula in sub:
                                if formula.tag == "Formula":
                                    b["formulas"].append({"key": formula.get("key", ""), "probability": formula.get("probability", ""), "exitMethod": formula.get("exitMethod", "")})
                        elif sub.tag == "Value":
                            val: dict[str, Any] = {"key": sub.get("key", ""), "use": sub.get("use", "false") == "true"}
                            for vsub in sub:
                                if vsub.tag in ("Generated", "Predefined"):
                                    val[vsub.tag.lower()] = _element_to_dict(vsub)
                            b["values"].append(val)
                        elif sub.tag == "Predefined":
                            b["predefined_changed"] = sub.get("changed", "false") == "true"
                            predefined = []
                            for params in sub:
                                if params.tag == "Params":
                                    predefined.append({"name": params.get("name", ""), "weight": params.get("weight", "")})
                            b["predefined_sets"] = predefined
                    blocks.append(b)
            result["building_blocks"] = blocks
        elif tag == "OrderTypes":
            order_types = []
            for block in child:
                if block.tag == "Block":
                    order_types.append(_parse_block_summary(block))
            result["order_types"] = order_types
        elif tag == "ExitTypes":
            exit_types = []
            for block in child:
                if block.tag == "Block":
                    exit_types.append(_parse_block_summary(block))
            result["exit_types"] = exit_types
        elif tag == "CustomData":
            result["custom_data"] = {"showAll": child.get("showAll", "false")}
    return result


def _parse_block_summary(block: ET.Element) -> dict[str, Any]:
    """Resumen de un Block (para OrderTypes, ExitTypes)."""
    b: dict[str, Any] = {
        "key": block.get("key", ""),
        "use": block.get("use", "false") == "true",
        "probability": block.get("probability", ""),
        "category": block.get("category", ""),
        "params": [],
    }
    for sub in block:
        if sub.tag == "Generated":
            for param in sub:
                if param.tag == "Param":
                    key = param.get("key", "")
                    name = param.get("name", key)
                    value, typ = _parse_value(param.text)
                    b["params"].append({"key": key, "name": name, "value": value, "type": typ})
        elif sub.tag == "Predefined":
            b["predefined_changed"] = sub.get("changed", "false") == "true"
    return b


def _parse_atms(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {"enable": el.get("enable", "false") == "true", "scaleOutType": el.get("scaleOutType", ""), "sizeDecimals": el.get("sizeDecimals", ""), "minSize": el.get("minSize", "")}
    for child in el:
        if child.tag == "ATM":
            result["atm"] = {"id": child.get("id", "")}
            for sub in child:
                if sub.tag == "Exits":
                    result["atm"]["exits"] = _element_to_dict(sub)
        elif child.tag == "GenerateConfig":
            types = {}
            for sub in child:
                if sub.tag == "Types":
                    for t in sub:
                        types[t.tag] = {k: v for k, v in t.attrib.items()}
                elif sub.tag == "Scenarios":
                    for s in sub:
                        types[s.tag] = {k: v for k, v in s.attrib.items()}
            result["generate_config"] = types
    return result


def _parse_databanks(el: ET.Element) -> dict[str, Any]:
    dbs = [{"label": c.get("label", ""), "name": c.get("name", ""), "value": c.get("value", "")} for c in el if c.tag == "Databank"]
    return {"retestSelected": el.get("retestSelected", "false") == "true", "databanks": dbs}


def _parse_resources(el: ET.Element) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for child in el:
        tag = child.tag
        if tag == "Symbols":
            symbols = []
            for sym in child:
                if sym.tag == "Symbol":
                    s: dict[str, Any] = {"name": sym.get("name", ""), "source": sym.get("source", ""), "barType": sym.get("barType", ""), "precision": sym.get("precision", "")}
                    for sub in sym:
                        if sub.tag == "InstrumentInfo":
                            s["instrument_info"] = {"instrument": sub.get("instrument", ""), "description": sub.get("description", ""), "tickSize": sub.get("tickSize", ""), "tickStep": sub.get("tickStep", "")}
                    symbols.append(s)
            result["symbols"] = symbols
        elif tag == "Brokers":
            result["brokers"] = [{"id": c.get("id", ""), "name": c.get("name", ""), "description": c.get("description", ""), "timezone": c.get("timezone", "")} for c in child if c.tag == "Broker"]
        elif tag == "Instruments":
            result["instruments"] = [{"instrument": c.get("instrument", ""), "description": c.get("description", ""), "tickSize": c.get("tickSize", ""), "tickStep": c.get("tickStep", "")} for c in child if c.tag == "InstrumentInfo"]
    return result


def _element_to_dict(el: ET.Element) -> Any:
    """Convierte un elemento XML a diccionario recursivamente."""
    result: dict[str, Any] = {}
    if el.attrib:
        result["@attributes"] = dict(el.attrib)
    children = list(el)
    if children:
        for child in children:
            tag = child.tag
            child_data = _element_to_dict(child)
            if tag in result:
                if not isinstance(result[tag], list):
                    result[tag] = [result[tag]]
                result[tag].append(child_data)
            else:
                result[tag] = child_data
    elif el.text and el.text.strip():
        return el.text.strip()
    return result
