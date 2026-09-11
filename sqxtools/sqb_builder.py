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

import difflib
import json
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

# Categorías de BuildingBlocks soportadas
BLOCK_CATEGORIES = ("signals", "indicators", "stopLimitBlocks")


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
    strict: bool = False,
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
        strict: si True, aborta con ValueError si algún bloque pedido no existe
            (no se escribe el archivo). Evita generar un .sqb incompleto.

    Returns:
        Reporte con conteos y bloques activados / no encontrados

    Raises:
        ValueError: si strict=True y hay bloques válidos no encontrados.
    """
    root = load_sqb_template(template_path)

    # None = no especificado → dejar los bloques como están en el template.
    # [] = explícitamente vacío → desactivar todos.
    untouch = {
        "signals": use_signals is None,
        "indicators": use_indicators is None,
        "stopLimitBlocks": use_stops is None,
    }
    sig_set: set[str] = set(use_signals or [])
    ind_set: set[str] = set(use_indicators or [])
    stop_set: set[str] = set(use_stops or [])
    ot_untouched = use_order_types is None
    et_untouched = use_exit_types is None
    ot_set: set[str] = set(use_order_types or [])
    et_set: set[str] = set(use_exit_types or [])

    # Validación previa: nombres inexistentes + sugerencias, antes de tocar el árbol
    if strict:
        issues = validate_selection(
            template_path,
            signals=sig_set,
            indicators=ind_set,
            stops=stop_set,
            order_types=ot_set,
            exit_types=et_set,
        )
        if issues["errors"]:
            detail = "\n".join(
                f"  - [{cat}] '{name}'{_suggestion_suffix(sug)}"
                for cat, name, sug in issues["errors"]
            )
            raise ValueError(
                "Bloques inválidos — no se generó el .sqb:\n" + detail
            )

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
            elif disable_rest and not untouch.get(category, False):
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
            elif disable_rest and not ot_untouched:
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
            elif disable_rest and not et_untouched:
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


def _suggestion_suffix(suggestion: str | None) -> str:
    """Formatea la sugerencia de un nombre inválido."""
    return f"  → ¿quisiste decir '{suggestion}'?" if suggestion else ""


def _catalog_keys(template_path: str | Path) -> dict[str, list[str]]:
    """Devuelve los keys válidos por contenedor.

    Returns:
        {"signals": [...], "indicators": [...], "stopLimitBlocks": [...],
         "orderTypes": [...], "exitTypes": [...]}
    """
    root = load_sqb_template(template_path)
    result: dict[str, list[str]] = {cat: [] for cat in BLOCK_CATEGORIES}

    bb = root.find("BuildingBlocks")
    if bb is not None:
        for block in bb:
            if _clean(block.tag) != "Block":
                continue
            cat = block.get("category", "")
            if cat in result:
                result[cat].append(block.get("key", ""))

    for tag, out_key in (("OrderTypes", "orderTypes"), ("ExitTypes", "exitTypes")):
        el = root.find(tag)
        result[out_key] = []
        if el is not None:
            for block in el:
                if _clean(block.tag) == "Block":
                    result[out_key].append(block.get("key", ""))

    return result


def validate_selection(
    template_path: str | Path,
    signals: list[str] | set[str] | None = None,
    indicators: list[str] | set[str] | None = None,
    stops: list[str] | set[str] | None = None,
    order_types: list[str] | set[str] | None = None,
    exit_types: list[str] | set[str] | None = None,
) -> dict:
    """Valida los nombres elegidos contra el catálogo real ANTES de generar el .sqb.

    Devuelve las faltantes con sugerencias (fuzzy matching) para corregir nombres
    mal escritos o que no existen en la versión de StrategyQuant del usuario.

    Returns:
        {
          "ok": bool,
          "errors": [(categoria, nombre, sugerencia|None), ...],
          "valid": {categoria: [nombres válidos]},
        }
    """
    catalog = _catalog_keys(template_path)

    checks: list[tuple[str, str, set[str] | None]] = [
        ("signals", "signals", set(signals) if signals else None),
        ("indicators", "indicators", set(indicators) if indicators else None),
        ("stopLimitBlocks", "stopLimitBlocks", set(stops) if stops else None),
        ("orderTypes", "orderTypes", set(order_types) if order_types else None),
        ("exitTypes", "exitTypes", set(exit_types) if exit_types else None),
    ]

    errors: list[tuple[str, str, str | None]] = []
    valid: dict[str, list[str]] = {}

    for category, source_key, names in checks:
        if not names:
            continue
        available = catalog.get(source_key, [])
        valid[category] = []
        for name in sorted(names):
            if name in available:
                valid[category].append(name)
            else:
                matches = difflib.get_close_matches(name, available, n=1, cutoff=0.6)
                errors.append((category, name, matches[0] if matches else None))

    return {
        "ok": not errors,
        "errors": errors,
        "valid": valid,
    }


def diff_sqb(path_a: str | Path, path_b: str | Path) -> dict:
    """Compara dos .sqb y devuelve qué bloques se activan/desactivan entre ellos.

    Args:
        path_a: .sqb de referencia (p. ej. el actual)
        path_b: .sqb nuevo (p. ej. el recomendado)

    Returns:
        Diff por categoría con bloques activados, desactivados y sin cambios,
        más los cambios en OrderTypes y ExitTypes.
    """
    root_a = load_sqb_template(path_a)
    root_b = load_sqb_template(path_b)

    diff: dict = {
        "file_a": Path(path_a).name,
        "file_b": Path(path_b).name,
        "categories": {},
        "order_types": {},
        "exit_types": {},
        "summary": {},
    }

    total_activated = 0
    total_deactivated = 0

    # === BuildingBlocks por categoría ===
    for cat in BLOCK_CATEGORIES:
        active_a = _active_keys(root_a, cat, container="BuildingBlocks")
        active_b = _active_keys(root_b, cat, container="BuildingBlocks")

        activated = sorted(active_b - active_a)
        deactivated = sorted(active_a - active_b)
        unchanged = sorted(active_a & active_b)

        total_activated += len(activated)
        total_deactivated += len(deactivated)

        diff["categories"][cat] = {
            "active_before": len(active_a),
            "active_after": len(active_b),
            "activated": activated,
            "deactivated": deactivated,
            "unchanged": len(unchanged),
        }

    # === OrderTypes / ExitTypes ===
    for tag, out_key in (("OrderTypes", "order_types"), ("ExitTypes", "exit_types")):
        before = _active_keys(root_a, None, container=tag)
        after = _active_keys(root_b, None, container=tag)
        diff[out_key] = {
            "before": sorted(before),
            "after": sorted(after),
            "activated": sorted(after - before),
            "deactivated": sorted(before - after),
        }

    diff["summary"] = {
        "blocks_activated": total_activated,
        "blocks_deactivated": total_deactivated,
        "has_changes": bool(
            total_activated or total_deactivated
            or diff["order_types"]["activated"] or diff["order_types"]["deactivated"]
            or diff["exit_types"]["activated"] or diff["exit_types"]["deactivated"]
        ),
    }

    return diff


def _active_keys(root: ET.Element, category: str | None, container: str) -> set[str]:
    """Keys de bloques con use=true dentro de un contenedor (opcionalmente por categoría)."""
    el = root.find(container)
    if el is None:
        return set()
    keys: set[str] = set()
    for block in el:
        if _clean(block.tag) != "Block":
            continue
        if block.get("use") != "true":
            continue
        if category is not None and block.get("category") != category:
            continue
        keys.add(block.get("key", ""))
    return keys


# === Perfiles de selección (YAML/JSON) ===

PROFILE_KEYS = ("signals", "indicators", "stopLimitBlocks", "order_types", "exit_types")


def load_profile(path: str | Path) -> dict:
    """Carga un perfil de bloques desde YAML o JSON.

    Estructura esperada:
        signals: [RSIFalling, ADXHigher]
        indicators: [Indicators.RSI, Prices.Close]
        stopLimitBlocks: [Stop/Limit Price Ranges.ATR]
        order_types: [EnterAtStop]
        exit_types: [StopLoss.StopLoss]
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"No existe el perfil: {p}")

    text = p.read_text(encoding="utf-8")
    suffix = p.suffix.lower()

    data: dict
    if suffix in (".yaml", ".yml"):
        try:
            import yaml
        except ImportError:
            raise ImportError(
                "El perfil es YAML pero pyyaml no está instalado. "
                "Instala con: pip install pyyaml  (o usá un perfil .json)"
            )
        data = yaml.safe_load(text) or {}
    else:
        data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError(f"El perfil debe ser un objeto con claves {PROFILE_KEYS}")

    profile: dict[str, list[str]] = {}
    for key in PROFILE_KEYS:
        val = data.get(key, [])
        if isinstance(val, str):
            val = [x.strip() for x in val.split(",") if x.strip()]
        if not isinstance(val, list):
            raise ValueError(f"El campo '{key}' del perfil debe ser una lista")
        profile[key] = [str(x) for x in val]

    # Metadatos opcionales (nombre, descripción) se preservan si existen
    for meta in ("name", "description", "symbol", "timeframe"):
        if meta in data:
            profile[meta] = data[meta]

    return profile


def save_profile(path: str | Path, profile: dict) -> Path:
    """Guarda un perfil a YAML (si hay pyyaml) o JSON."""
    p = Path(path)
    payload = {k: v for k, v in profile.items() if k in PROFILE_KEYS or k in ("name", "description", "symbol", "timeframe")}

    if p.suffix.lower() in (".yaml", ".yml"):
        try:
            import yaml
            p.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
            return p
        except ImportError:
            p = p.with_suffix(".json")

    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return p


def build_from_profile(
    template_path: str | Path,
    profile: dict | str | Path,
    output_path: str | Path,
    disable_rest: bool = True,
    strict: bool = True,
) -> dict:
    """Genera un .sqb recomendado a partir de un perfil (dict o ruta YAML/JSON)."""
    if isinstance(profile, (str, Path)):
        profile = load_profile(profile)

    report = build_recommended_sqb(
        template_path=template_path,
        output_path=output_path,
        use_signals=profile.get("signals"),
        use_indicators=profile.get("indicators"),
        use_stops=profile.get("stopLimitBlocks"),
        use_order_types=profile.get("order_types"),
        use_exit_types=profile.get("exit_types"),
        disable_rest=disable_rest,
        strict=strict,
    )
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