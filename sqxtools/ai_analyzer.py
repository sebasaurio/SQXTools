"""AI Analyzer — envía el resumen del .cfx a un LLM para análisis completo."""

import json
import os
from pathlib import Path
from typing import Any

from .analyzer import summarize


# Prompt de sistema para el modelo de análisis
SYSTEM_PROMPT = """Eres un experto en trading algorítmico y StrategyQuant. Tu trabajo es analizar configuraciones de builder (.cfx) y proponer mejoras concretas y accionables.

Analiza:
1. **Indicadores y bloques activos**: detecta redundancias, conflictos, combinaciones débiles, oportunidades perdidas.
2. **Risk Management**: evalúa SL/PT, money management, drawdown máximo. Propone ajustes si es necesario.
3. **Robustness**: verifica que haya cross-checks habilitados (Walk-Forward, Monte Carlo, etc.). Sugiere habilitar los falten.
4. **Mejoras concretas**: propón bloques adicionales que podrían mejorar la estrategia, parámetros a optimizar, condiciones de ranking más estrictas.

Formato de salida (obligatorio):
## Resumen Ejecutivo
[2-3 frases del estado actual]

## Análisis Técnico
[Indicadores redundantes o faltantes, conflictos detectados]

## Risk Management
[Evaluación de SL/PT/MM, propuestas de ajuste]

## Robustness
[Cross-checks habilitados vs recomendados]

## Mejoras Propuestas
[Lista numerada de cambios concretos con justificación]

## Plan de Acción Sugerido
[Pasos recomendados en orden de prioridad]

Sé específico y accionable. Evita generalidades."""


def build_analysis_prompt(summary: dict[str, Any]) -> str:
    """Construye el prompt de usuario con el resumen del .cfx."""
    return f"""Analiza esta configuración de StrategyQuant:

```json
{json.dumps(summary, indent=2, ensure_ascii=False, default=str)}
```

Proporciona el análisis completo siguiendo el formato indicado."""


def analyze_with_openai(summary: dict[str, Any], api_key: str | None = None, model: str = "gpt-4o") -> str:
    """Analiza usando OpenAI API."""
    import urllib.request
    
    key = api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY no configurada. Exporta la variable o pásala por argumento.")
    
    prompt = build_analysis_prompt(summary)
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4000,
    }
    
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    
    return data["choices"][0]["message"]["content"]


def analyze_with_anthropic(summary: dict[str, Any], api_key: str | None = None, model: str = "claude-sonnet-4-20250514") -> str:
    """Analiza usando Anthropic API."""
    import urllib.request
    
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY no configurada. Exporta la variable o pásala por argumento.")
    
    prompt = build_analysis_prompt(summary)
    
    payload = {
        "model": model,
        "max_tokens": 4000,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": prompt}],
    }
    
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "x-api-key": key,
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        },
    )
    
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    
    return data["content"][0]["text"]


def analyze_with_mistral(summary: dict[str, Any], api_key: str | None = None, model: str = "mistral-large-latest") -> str:
    """Analiza usando Mistral API."""
    import urllib.request
    
    key = api_key or os.environ.get("MISTRAL_API_KEY")
    if not key:
        raise ValueError("MISTRAL_API_KEY no configurada. Exporta la variable o pásala por argumento.")
    
    prompt = build_analysis_prompt(summary)
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 4000,
    }
    
    req = urllib.request.Request(
        "https://api.mistral.ai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        },
    )
    
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    
    return data["choices"][0]["message"]["content"]


PROVIDERS = {
    "openai": analyze_with_openai,
    "anthropic": analyze_with_anthropic,
    "mistral": analyze_with_mistral,
}


def analyze(cfg_summary: dict[str, Any], provider: str = "anthropic", api_key: str | None = None, model: str | None = None) -> str:
    """Analiza con el proveedor elegido."""
    fn = PROVIDERS.get(provider)
    if not fn:
        raise ValueError(f"Proveedor no soportado: {provider}. Opciones: {list(PROVIDERS.keys())}")
    
    kwargs: dict[str, Any] = {"api_key": api_key}
    if model:
        kwargs["model"] = model
    
    return fn(cfg_summary, **kwargs)
