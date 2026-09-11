"""Serializador del modelo CfxConfig a formatos de salida."""

import json
from pathlib import Path
from typing import Any

from .models import CfxConfig


def to_json(cfg: CfxConfig, indent: int = 2) -> str:
    """Serializa a JSON."""
    return json.dumps(cfg.to_dict(), indent=indent, ensure_ascii=False, default=str)


def to_yaml(cfg: CfxConfig) -> str:
    """Serializa a YAML (sin dependencias externas)."""
    try:
        import yaml
        return yaml.dump(cfg.to_dict(), default_flow_style=False, allow_unicode=True, sort_keys=False)
    except ImportError:
        # Fallback: YAML-like manual
        return _to_yaml_like(cfg.to_dict())


def _to_yaml_like(data: Any, indent: int = 0) -> str:
    """Genera YAML-like sin dependencias."""
    lines = []
    prefix = "  " * indent
    if isinstance(data, dict):
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines.append(_to_yaml_like(v, indent + 1))
            else:
                lines.append(f"{prefix}{k}: {_yaml_scalar(v)}")
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    if isinstance(v, (dict, list)):
                        if first:
                            lines.append(f"{prefix}- {k}:")
                            first = False
                        else:
                            lines.append(f"{prefix}  {k}:")
                        lines.append(_to_yaml_like(v, indent + 2))
                    else:
                        if first:
                            lines.append(f"{prefix}- {k}: {_yaml_scalar(v)}")
                            first = False
                        else:
                            lines.append(f"{prefix}  {k}: {_yaml_scalar(v)}")
            else:
                lines.append(f"{prefix}- {_yaml_scalar(item)}")
    return "\n".join(lines)


def _yaml_scalar(v: Any) -> str:
    """Escalar YAML seguro."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    if any(c in s for c in ":{}[]&*?|-><!%@`") or s.startswith(" ") or s.endswith(" "):
        return f'"{s}"'
    return s


def to_markdown(cfg: CfxConfig) -> str:
    """Serializa a Markdown estructurado (legible para IA)."""
    lines = [
        f"# {cfg.filename}",
        f"**Tipo:** {cfg.cfx_type.value}  ",
        f"**Versión:** {cfg.version or 'n/a'}",
        "",
    ]
    if cfg.metadata:
        lines.append("## Metadata")
        for k, v in cfg.metadata.items():
            lines.append(f"- **{k}:** {v}")
        lines.append("")
    if cfg.settings:
        lines.extend(_section_md("Settings", cfg.settings))
    if cfg.what_to_build:
        lines.extend(_section_md("WhatToBuild", cfg.what_to_build))
    if cfg.data:
        lines.extend(_section_md("Data", cfg.data))
    if cfg.rankings:
        lines.extend(_section_md("Rankings", cfg.rankings))
    if cfg.blocks:
        lines.extend(_section_md("Blocks", cfg.blocks))
    return "\n".join(lines)


def _section_md(name: str, data: dict, level: int = 2) -> list[str]:
    lines = [f"{'#' * level} {name}"]
    for k, v in data.items():
        if isinstance(v, dict):
            lines.append(f"- **{k}:**")
            for k2, v2 in v.items():
                lines.append(f"  - {k2}: {v2}")
        elif isinstance(v, list):
            lines.append(f"- **{k}:** ({len(v)} items)")
            for i, item in enumerate(v[:10]):
                lines.append(f"  - {item}")
            if len(v) > 10:
                lines.append(f"  - ... y {len(v) - 10} más")
        else:
            lines.append(f"- **{k}:** {v}")
    lines.append("")
    return lines


def save_output(cfg: CfxConfig, out_path: str | Path) -> Path:
    """Guarda en el formato según la extensión (.json / .md / .yaml)."""
    p = Path(out_path)
    suffix = p.suffix.lower()
    if suffix == ".json":
        p.write_text(to_json(cfg), encoding="utf-8")
    elif suffix in (".md", ".markdown"):
        p.write_text(to_markdown(cfg), encoding="utf-8")
    elif suffix in (".yaml", ".yml"):
        p.write_text(to_yaml(cfg), encoding="utf-8")
    else:
        p.write_text(to_json(cfg), encoding="utf-8")
    return p
