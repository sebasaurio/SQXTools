"""Modelo canónico para configs de StrategyQuant."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CfxType(str, Enum):
    BUILDING_CONFIG = "building_config"
    BUILD = "build"
    RETESTER = "retester"
    OPTIMIZER = "optimizer"
    CUSTOM_PROJECT = "custom_project"
    INFO = "info"
    UNKNOWN = "unknown"


@dataclass
class Param:
    key: str
    name: str
    value: Any
    type: str = "string"
    className: str = ""


@dataclass
class Condition:
    use: bool = False
    left_side: dict[str, Any] = field(default_factory=dict)
    comparator: str = ""
    right_side: dict[str, Any] = field(default_factory=dict)


@dataclass
class Block:
    key: str
    weight: str = "1"
    use: bool = False
    category: str = ""
    params: list[Param] = field(default_factory=list)
    formulas: list[dict[str, str]] = field(default_factory=list)
    values: list[dict[str, Any]] = field(default_factory=list)
    predefined_changed: bool = False


@dataclass
class Setup:
    dateFrom: str = ""
    dateTo: str = ""
    testPrecision: str = ""
    session: str = ""
    charts: list[dict[str, str]] = field(default_factory=list)
    commissions: dict[str, Any] = field(default_factory=dict)
    swap: dict[str, Any] = field(default_factory=dict)


@dataclass
class Range:
    dateFrom: str = ""
    dateTo: str = ""
    type: str = ""


@dataclass
class CfxConfig:
    """Modelo canónico de un archivo .cfx."""
    filename: str = ""
    cfx_type: CfxType = CfxType.UNKNOWN
    version: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    settings: dict[str, Any] = field(default_factory=dict)
    what_to_build: dict[str, Any] = field(default_factory=dict)
    risk_money_management: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    rankings: dict[str, Any] = field(default_factory=dict)
    parts_to_improve: dict[str, Any] = field(default_factory=dict)
    cross_checks: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    blocks: dict[str, Any] = field(default_factory=dict)
    atms: dict[str, Any] = field(default_factory=dict)
    databanks: dict[str, Any] = field(default_factory=dict)
    resources: dict[str, Any] = field(default_factory=dict)
    raw_sections: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "filename": self.filename,
            "cfx_type": self.cfx_type.value,
            "version": self.version,
            "metadata": self.metadata,
            "settings": self.settings,
            "what_to_build": self.what_to_build,
            "risk_money_management": self.risk_money_management,
            "data": self.data,
            "rankings": self.rankings,
            "parts_to_improve": self.parts_to_improve,
            "cross_checks": self.cross_checks,
            "notes": self.notes,
            "blocks": self.blocks,
            "atms": self.atms,
            "databanks": self.databanks,
            "resources": self.resources,
            "raw_sections": self.raw_sections,
        }


# === Modelos para archivos .sqb (Block Settings) ===

@dataclass
class SqbParam:
    """Sección Generated de un bloque."""
    weight: str = "1"
    params: list[dict] = field(default_factory=list)


@dataclass
class SqbPredefined:
    """Sección Predefined de un bloque."""
    changed: bool = False
    sets: list[dict] = field(default_factory=list)


@dataclass
class SqbBlock:
    """Un bloque en el archivo .sqb."""
    key: str
    weight: str = "1"
    use: bool = False
    category: str = ""
    indicator_min: str = None
    indicator_max: str = None
    generated: SqbParam = None
    predefined: SqbPredefined = None


@dataclass
class SqbFile:
    """Modelo canónico de un archivo .sqb."""
    filename: str = ""
    block_type: str = "simple"
    version: str = ""
    calibration: dict[str, str] = field(default_factory=dict)
    building_blocks: list[SqbBlock] = field(default_factory=list)
    order_types: list[SqbBlock] = field(default_factory=list)
    exit_types: list[SqbBlock] = field(default_factory=list)
    custom_data: dict[str, str] = field(default_factory=dict)
