"""Serializador del modelo CfxConfig a formatos de salida."""

import json
from pathlib import Path

from .models import CfxConfig


def to_json(cfg: CfxConfig, indent: int = 2) -> str:
    """Serializa a JSON."""
    return json.dumps(cfg.to_dict(), indent=indent, ensure_ascii=False, default=str)


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
    """Guarda en el formato según la extensión (.json / .md)."""
    p = Path(out_path)
    if p.suffix.lower() == ".json":
        p.write_text(to_json(cfg), encoding="utf-8")
    elif p.suffix.lower() in (".md", ".markdown"):
        p.write_text(to_markdown(cfg), encoding="utf-8")
    else:
        p.write_text(to_json(cfg), encoding="utf-8")
    return p
