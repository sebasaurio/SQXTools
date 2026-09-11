"""AI Analyzer — prepara el resumen para que el agente analice directamente."""

import json
import sys
from pathlib import Path
from typing import Any

from .analyzer import summarize
from .parser import parse_cfx


# Prompt de sistema que el agente usa para analizar
SYSTEM_PROMPT = """Eres un experto en trading algorítmico y StrategyQuant. Tu trabajo es analizar configuraciones de builder (.cfx) y proponer mejoras concretas y accionables.

Analiza:
1. **Indicadores y bloques activos**: detecta redundancias, conflictos, combinaciones débiles, oportunidades perdidas.
2. **Risk Management**: evalúa SL/PT, money management, drawdown máximo. Propone ajustes si es necesario.
3. **Robustness (SOLO si cross-check global está activo)**: si cross_checks.use=true, verifica qué individuales están habilitados y recomienda activar los falten. Si cross_checks.use=false, omite completamente esta sección — el usuario decidió no usar cross-checks y no es una alerta.
4. **Mejoras concretas**: propón bloques adicionales que podrían mejorar la estrategia, parámetros a optimizar, condiciones de ranking más estrictas.

Formato de salida (obligatorio):
## Resumen Ejecutivo
[2-3 frases del estado actual]

## Análisis Técnico
[Indicadores redundantes o faltantes, conflictos detectados]

## Risk Management
[Evaluación de SL/PT/MM, propuestas de ajuste]

## Robustness (solo si cross_checks.use=true)
[Cross-checks habilitados vs recomendados. Si cross_checks.use=false, NO incluir esta sección.]

## Mejoras Propuestas
[Lista numerada de cambios concretos con justificación]

## Plan de Acción Sugerido
[Pasos recomendados en orden de prioridad]

Sé específico y accionable. Evita generalidades."""


def prepare_for_agent(cfx_path: str | Path, output_path: str | Path | None = None) -> Path:
    """Parsea el .cfx, genera el resumen y lo guarda para que el agente lo analice.
    
    Returns:
        Path al archivo de resumen generado.
    """
    cfg = parse_cfx(cfx_path)
    summary = summarize(cfg)
    
    out = Path(output_path) if output_path else Path(cfx_path).with_suffix(".ai_input.json")
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    return out


def get_system_prompt() -> str:
    """Retorna el prompt de sistema para el análisis."""
    return SYSTEM_PROMPT
