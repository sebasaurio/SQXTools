"""StrategyQuant .cfx parser — convierte configs en modelos canónicos."""

from .parser import parse_cfx
from .models import CfxConfig, CfxType

__all__ = ["parse_cfx", "CfxConfig", "CfxType"]
