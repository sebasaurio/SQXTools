"""SQXTools — parsea y analiza archivos .cfx/.sqb de StrategyQuant.

Permite convertir configs del Builder y Building Blocks a modelos legibles por IA,
analizarlos, compararlos y generar configuraciones optimizadas.
"""

from .parser import parse_cfx
from .models import CfxConfig, CfxType, Param, Condition, Block, Setup, Range
from .analyzer import summarize, active_blocks_only, blocks_by_category
from .compare import compare_configs
from .serializer import to_json, to_markdown, to_yaml, save_output
from .ai_analyzer import get_system_prompt, prepare_for_agent
from .data_downloader import download_dukascopy, download_yfinance, load_data
from .edge_analyzer import analyze_market
from .date_optimizer import optimize_date_ranges
from .sqb_parser import parse_sqb, get_block_summary as sqb_block_summary
from .sqb_builder import (
    build_recommended_sqb,
    get_block_definition,
    dump_catalog,
    list_blocks,
)

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
    "get_system_prompt",
    "prepare_for_agent",
    "download_dukascopy",
    "download_yfinance",
    "load_data",
    "analyze_market",
    "optimize_date_ranges",
    "parse_sqb",
    "sqb_block_summary",
    "build_recommended_sqb",
    "get_block_definition",
    "dump_catalog",
    "list_blocks",
]
