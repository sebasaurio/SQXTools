# SQXTools

Parser y analizador de archivos **.cfx** de StrategyQuant — convierte building config, build, retester, optimizer, custom project e info en **JSON/Markdown/YAML legible para IA**.

## ¿Qué hace?

Los archivos `.cfx` de StrategyQuant son ZIP con un `config.xml` interno que contiene toda la configuración de un proyecto de trading algorítmico: bloques de indicadores (building blocks), reglas de entrada/salida, gestión de riesgo, cross checks, recursos (símbolos, brokers, instrumentos), etc.

**SQXTools** extrae ese XML y lo convierte en un modelo canónico estructurado que una IA (o un humano) puede leer fácilmente.

## Instalación

```bash
pip install -e .
```

## Uso rápido

```bash
# Parsear un .cfx a JSON completo
python -m sqxtools.cli parse archivo.cfx -o output.json

# Parsear a YAML
python -m sqxtools.cli parse archivo.cfx -o output.yaml

# Parsear a Markdown
python -m sqxtools.cli parse archivo.cfx -o output.md

# Generar resumen ejecutivo (ideal para IA)
python -m sqxtools.cli analyze archivo.cfx -o resumen.json

# Ver solo bloques activos
python -m sqxtools.cli filter archivo.cfx --active-only

# Filtrar por categoría (signals, indicators, stopLimitBlocks)
python -m sqxtools.cli filter archivo.cfx --active-only --category signals

# Listar categorías disponibles
python -m sqxtools.cli list-categories archivo.cfx

# Comparar dos .cfx (qué bloques cambian, qué SLPT difiere, etc.)
python -m sqxtools.cli compare build1.cfx build2.cfx -o diff.json
```

## Salida JSON — Estructura

```json
{
  "filename": "Build strategies 1.cfx",
  "cfx_type": "build",
  "version": "144.2938",
  "metadata": { "name": "Build strategies 1", ... },
  "settings": {
    "trading_options": [
      { "key": "ExitOnFriday", "name": "Exit On Friday", "value": true, "type": "bool" }
    ]
  },
  "what_to_build": {
    "strategy_type": { "type": "simple", "additionalCharts": "2" },
    "rules_complexity": { "charts": [...] },
    "market_sides": { "type": "short" },
    "slpt_options": { "SLRequired": true, "PTRequired": true, ... },
    "build_mode": { "generationType": "genetic-evolution", "PopulationSize": "25", ... }
  },
  "data": {
    "setups": [{ "dateFrom": "...", "dateTo": "...", "charts": [...] }],
    "out_of_sample": { "ranges": [...] }
  },
  "rankings": {
    "max_strategies": "1000",
    "fitness_criteria": { "type": "ReturnDDRatio" },
    "conditions": [{ "use": true, "left_side": {...}, "comparator": ">", "right_side": {...} }],
    ...
  },
  "blocks": {
    "calibration": "...",
    "building_blocks": [
      {
        "key": "ADXChangesDown",
        "weight": "1",
        "use": true,
        "category": "signals",
        "params": [{ "key": "#Period#", "name": "Period", "value": 14, "type": "int" }],
        "formulas": [],
        "values": [],
        "predefined_sets": [{ "name": "Default set 1", "weight": "1" }]
      }
    ],
    "order_types": [...],
    "exit_types": [...]
  },
  "resources": {
    "symbols": [{ "name": "USATECHIDXUSD_exness", "instrument_info": {...} }],
    "brokers": [{ "name": "[Exness]" }],
    "instruments": [...]
  }
}
```

## Salida Analyze — Resumen para IA

```bash
python -m sqxtools.cli analyze archivo.cfx -o resumen.json
```

Genera un resumen compacto pensado para que una IA lo procese fácilmente:

```json
{
  "type": "build",
  "blocks_summary": { "total": 524, "active": 110, "inactive": 414 },
  "categories": { "stopLimitBlocks": 39, "indicators": 37, "signals": 34 },
  "active_by_category": { "signals": ["ADXChangesDown", ...], ... },
  "strategy_type": "simple",
  "market_sides": "short",
  "slpt": { "sl_required": true, "pt_required": true, ... },
  "build_mode": { "type": "genetic-evolution", "population_size": "25", ... },
  "data": { "num_setups": 1, "out_of_sample_ranges": 4, "charts": [...] },
  "rankings": { "type": "never", "max_strategies": "1000", "active_filters": [...] },
  "cross_checks": { "enabled": [] },
  "indicators": [{ "name": "ADXChangesDown", "category": "signals", "params": [...] }],
  "resources": { "symbols": ["USATECHIDXUSD_exness"], "brokers": ["[Exness]"] }
}
```

## Comparar dos .cfx

```bash
python -m sqxtools.cli compare build1.cfx build2.cfx -o diff.json
```

```json
{
  "file1": "build1.cfx",
  "file2": "build2.cfx",
  "blocks": {
    "active1": 110, "active2": 72, "common": 69,
    "only_in_file1": ["ADXCrossDown", "BollingerBandsInside", ...],
    "only_in_file2": ["NewIndicator"]
  },
  "categories": {
    "differences": { "signals": 5, "indicators": -2 }
  },
  "slpt_options_diff": {
    "MaxSLATRMultiple": { "file1": "5", "file2": "3" }
  }
}
```

## API Python

```python
from sqxtools import parse_cfx, summarize, active_blocks_only, compare_configs, to_json, to_yaml

# Parsear
cfg = parse_cfx("Build strategies 1.cfx")

# Analizar
summary = summarize(cfg)
active = active_blocks_only(cfg)
signals = blocks_by_category(cfg, "signals", active_only=True)

# Serializar
json_str = to_json(cfg)
yaml_str = to_yaml(cfg)

# Comparar
diff = compare_configs(cfg1, cfg2)
```

## Tests

```bash
python -m pytest sqxtools/tests/ -v
```

Los tests incluyen fixtures reales (2 archivos `.cfx` de ejemplo).

## Soporte de tipos

| Extensión | Tipo detectado | Descripción |
|-----------|---------------|-------------|
| `.cfx` | `build` | Configuración de build |
| `.cfx` | `retester` | Configuración de retester |
| `.cfx` | `optimizer` | Configuración de optimizer |
| `.cfx` | `buildingconfig` | Building config |
| `.cfx` | `customproject` | Custom project |
| `.cfx` | `info` | Info de estrategia |

## Estructura del proyecto

```
SQXTools/
├── sqxtools/
│   ├── __init__.py         # API pública
│   ├── parser.py           # Parser del XML → modelo
│   ├── models.py           # Dataclasses del modelo
│   ├── analyzer.py         # Resumen ejecutivo
│   ├── compare.py          # Comparador de configs
│   ├── serializer.py       # JSON / Markdown / YAML
│   ├── cli.py              # Interfaz CLI
│   └── tests/
│       ├── test_parser.py  # Tests unitarios
│       ├── test_real_files.py  # Tests con .cfx reales
│       ├── conftest.py
│       └── fixtures/       # .cfx de ejemplo
├── README.md
└── setup.py
```

## Licencia

MIT
