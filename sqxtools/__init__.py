"""StrategyQuant .cfx parser — convierte configs en modelos canónicos."""

from .parser import parse_cfx
from .models import CfxConfig, CfxType, Param, Condition, Block, Setup, Range
from .analyzer import summarize, active_blocks_only, blocks_by_category
from .compare import compare_configs
from .serializer import to_json, to_markdown, to_yaml, save_output
from .ai_analyzer import get_system_prompt, prepare_for_agent

__all__ = [
    "parse_cfx",
    "CfxConfig",
    "CfxType",
    "Param",
    "Condition",
    "Block",
    "Setup",
    "Range",
    "summarize",
    "active_blocks_only",
    "blocks_by_category",
    "compare_configs",
    "to_json",
    "to_markdown",
    "to_yaml",
    "save_output",
    "ai_analyze",
]
