"""SQB Builder — genera un .sqb recomendado usando el catálogo completo como plantilla.

ENFOQUE CORRECTO:
  En lugar de inventar bloques con parámetros aproximados (que StrategyQuant rechaza
  porque la firma de params no coincide con la definición real del bloque), este módulo:

  1. Lee el .sqb ORIGEN completo (que contiene los 524 bloques con su firma exacta de
     parámetros: #Chart#, #Period#, #ComputedFrom#, #Mode#, #ATRPeriod#, etc.)
  2. Marca use="true" SOLO en los bloques recomendados
  3. Marca use="false" en el resto
  4. Escribe el archivo completo preservando la estructura original

  Esto garantiza que StrategyQuant cargue y marque correctamente los bloques, porque
  cada bloque mantiene sus parámetros y Predefined sets originales intactos.

Por qué es necesario:
  StrategyQuant valida la firma de parámetros de cada bloque contra su definición
  interna. Si un bloque tiene parámetros que no existen (ej. #Level# en RSIFalling,
  que en realidad usa #ComputedFrom#), SQ no lo reconoce y queda sin marcar.
"""

import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def _clean(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def load_sqb_template(path: str | Path) -> ET.Element:
    """Carga el árbol XML de un .sqb (ZIP con config.xml)."""
    with zipfile.ZipFile(path) as z:
        if "config.xml" not in z.namelist():
            raise ValueError(f"{path} no contiene config.xml")
        with z.open("config.xml") as f:
            return ET.parse(f).getroot()


def list_blocks(root: ET.Element, category: str | None = None) -> list[str]:
    """Lista los keys de bloques disponibles en el catálogo."""
    bb = root.find("BuildingBlocks")
    if bb is None:
        return []
    keys = []
    for block in bb:
        if _clean(block.tag) != "Block":
            continue
        if category and block.get("category") != category:
            continue
        keys.append(block.get("key", ""))
    return keys


def build_recommended_sqb(
    template_path: str | Path,
    output_path: str | Path,
    use_signals: list[str] | None = None,
    use_indicators: list[str] | None = None,
    use_stops: list[str] | None = None,
    use_order_types: list[str] | None = None,
    use_exit_types: list[str] | None = None,
    disable_rest: bool = True,
) -> dict:
    """Genera un .sqb recomendado a partir del catálogo origen.

    Args:
        template_path: .sqb origen con el catálogo completo (524 bloques)
        output_path: .sqb de salida
        use_signals: keys de bloques en categoría 'signals' a marcar use=true
        use_indicators: keys en 'indicators' a marcar
        use_stops: keys en 'stopLimitBlocks' a marcar
        use_order_types: keys en 'OrderTypes' a marcar
        use_exit_types: keys en 'ExitTypes' a marcar
        disable_rest: si True, marca use=false en todo lo demás (recomendado)

    Returns:
        Reporte con conteos y bloques activados / no encontrados
    """
    root = load_sqb_template(template_path)

    sig_set: set[str] = set(use_signals or [])
    ind_set: set[str] = set(use_indicators or [])
    stop_set: set[str] = set(use_stops or [])
    ot_set: set[str] = set(use_order_types or [])
    et_set: set[str] = set(use_exit_types or [])

    wanted: dict[str, set[str]] = {
        "signals": sig_set,
        "indicators": ind_set,
        "stopLimitBlocks": stop_set,
    }

    report: dict = {
        "activated": {"signals": [], "indicators": [], "stopLimitBlocks": []},
        "not_found": {"signals": [], "indicators": [], "stopLimitBlocks": []},
        "deactivated": 0,
        "order_types": [],
        "exit_types": [],
    }

    # === BuildingBlocks ===
    bb = root.find("BuildingBlocks")
    if bb is not None:
        found: dict[str, set[str]] = {"signals": set(), "indicators": set(), "stopLimitBlocks": set()}
        for block in bb:
            if _clean(block.tag) != "Block":
                continue
            category = block.get("category", "")
            key = block.get("key", "")

            if category in wanted and key in wanted[category]:
                block.set("use", "true")
                found[category].add(key)
                report["activated"][category].append(key)
            elif disable_rest:
                block.set("use", "false")
                report["deactivated"] += 1

        # Detectar bloques pedidos que no existen en el catálogo
        for category, keys in wanted.items():
            for key in keys:
                if key not in found[category]:
                    report["not_found"][category].append(key)

    # === OrderTypes ===
    ot = root.find("OrderTypes")
    if ot is not None:
        for block in ot:
            if _clean(block.tag) != "Block":
                continue
            key = block.get("key", "")
            if key in ot_set:
                block.set("use", "true")
                report["order_types"].append({"key": key, "use": "true"})
            elif disable_rest:
                block.set("use", "false")

    # === ExitTypes ===
    et = root.find("ExitTypes")
    if et is not None:
        for block in et:
            if _clean(block.tag) != "Block":
                continue
            key = block.get("key", "")
            if key in et_set:
                block.set("use", "true")
                report["exit_types"].append({"key": key, "use": "true"})
            elif disable_rest:
                block.set("use", "false")

    # === Escribir .sqb ===
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tree = ET.ElementTree(root)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        with zf.open("config.xml", "w") as f:
            tree.write(f, encoding="utf-8", xml_declaration=True)

    report["output"] = str(out_path)
    return report


def get_block_definition(template_path: str | Path, block_key: str) -> dict | None:
    """Devuelve la definición completa (params, tipo, valores) de un bloque del catálogo.

    Útil para que el agente sepa qué parámetros acepta cada bloque antes de recomendarlo.
    """
    root = load_sqb_template(template_path)
    bb = root.find("BuildingBlocks")
    if bb is None:
        return None

    for block in bb:
        if _clean(block.tag) != "Block" or block.get("key") != block_key:
            continue

        result = {
            "key": block_key,
            "category": block.get("category", ""),
            "weight": block.get("weight", "1"),
            "use": block.get("use") == "true",
            "indicatorMin": block.get("indicatorMin"),
            "indicatorMax": block.get("indicatorMax"),
            "indicatorStep": block.get("indicatorStep"),
            "params": [],
            "predefined_sets": 0,
        }

        gen = block.find("Generated")
        if gen is not None:
            for p in gen:
                if _clean(p.tag) != "Param":
                    continue
                result["params"].append({
                    "key": p.get("key", ""),
                    "name": p.get("name", ""),
                    "type": p.get("type", ""),
                    "generation": p.get("generation", ""),
                    "minValue": p.get("minValue"),
                    "maxValue": p.get("maxValue"),
                    "step": p.get("step"),
                    "values": p.get("values"),
                })

        pred = block.find("Predefined")
        if pred is not None:
            result["predefined_sets"] = sum(1 for s in pred if _clean(s.tag) == "Params")

        # Mostrar un ejemplo de valores por defecto del primer set Predefined
        if pred is not None:
            for s in pred:
                if _clean(s.tag) == "Params":
                    defaults = {}
                    for p in s:
                        if _clean(p.tag) == "Param" and p.get("generation") == "fixed":
                            defaults[p.get("key", "")] = p.get("defaultValue")
                    if defaults:
                        result["example_defaults"] = defaults
                    break

        return result

    return None


def dump_catalog(template_path: str | Path, category: str | None = None) -> list[dict]:
    """Devuelve el catálogo completo: key + params + valores válidos por bloque.

    Esto es lo que el agente debe consultar para recomendar bloques con la firma correcta.
    """
    root = load_sqb_template(template_path)
    bb = root.find("BuildingBlocks")
    catalog = []
    if bb is None:
        return catalog

    for block in bb:
        if _clean(block.tag) != "Block":
            continue
        cat = block.get("category", "")
        if category and cat != category:
            continue

        entry = {
            "key": block.get("key", ""),
            "category": cat,
            "params": [],
        }
        gen = block.find("Generated")
        if gen is not None:
            for p in gen:
                if _clean(p.tag) != "Param":
                    continue
                param = {
                    "key": p.get("key", ""),
                    "type": p.get("type", ""),
                }
                if p.get("values"):
                    param["values"] = p.get("values")
                if p.get("minValue") and p.get("minValue") not in ("null", "-1000003", "-1000004", "-1000001", "-1000002"):
                    param["min"] = p.get("minValue")
                if p.get("maxValue") and p.get("maxValue") not in ("null", "-1000003", "-1000004", "-1000001", "-1000002"):
                    param["max"] = p.get("maxValue")
                if p.get("step") and p.get("step") not in ("null", "1"):
                    param["step"] = p.get("step")
                entry["params"].append(param)

        catalog.append(entry)

    return catalog