# SQXTools

Parser y analizador de archivos **.cfx** y **.sqb** de StrategyQuant — convierte building config, build, retester, optimizer, custom project, info y Block Settings en **JSON/Markdown/YAML legible para IA**. Incluye análisis de mercado, optimizador de fechas IS/OOS y generador de `.sqb` recomendado.

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

# Preparar el resumen para que el agente (IA de la sesión) lo analice
python -m sqxtools.cli ai-analyze archivo.cfx -o resumen_ai.json
```

### Análisis de mercado y generación de `.sqb`

```bash
# Analizar el mercado real y proponer un builder óptimo (Dukascopy o Yahoo Finance)
python -m sqxtools.cli edge-finder --symbol NAS100 --timeframe H1 --source dukascopy

# Proponer rangos IS/OOS óptimos según regímenes de volatilidad
python -m sqxtools.cli date-optimizer --symbol NAS100 --timeframe H1 --source dukascopy

# Análisis completo: mercado + fechas + builder (todo integrado)
python -m sqxtools.cli full-analysis --symbol NAS100 --timeframe H1 --source dukascopy

# Ver el catálogo real de bloques y su firma EXACTA de parámetros
python -m sqxtools.cli catalog --template BlockSettings.sqb --category signals
python -m sqxtools.cli catalog --template BlockSettings.sqb --block RSIFalling

# Generar un .sqb recomendado desde el catálogo origen
# (preserva la firma exacta de parámetros de cada bloque; solo cambia use=true/false)
# Valida los nombres ANTES de escribir y aborta si alguno no existe en el catálogo.
python -m sqxtools.cli build-sqb --template BlockSettings.sqb -o salida.sqb \
  --signals "SuperTrendDownTrend,RSIFalling,ADXHigher" \
  --indicators "Indicators.RSI,Indicators.ATR,Prices.Close,IsGreater" \
  --stops "Stop/Limit Price Ranges.ATR" \
  --order-types "EnterAtStop,EnterAtLimit" \
  --exit-types "StopLoss.StopLoss,ProfitTarget.ProfitTarget"

# Con un perfil guardado (evita pasar listas largas por CLI)
python -m sqxtools.cli build-sqb --template BlockSettings.sqb \
  --profile perfiles/nas100-shorts.yaml -o salida.sqb

# Comparar el .sqb actual con el recomendado (qué se activa / desactiva)
python -m sqxtools.cli diff-sqb actual.sqb recomendado.sqb -o diff.json

# Aplicar un perfil de configuración a un .cfx del builder
python -m sqxtools.cli build-cfx --template v5.cfx \
  --profile perfiles/builder-nas100-winrate.yaml -o output/v6.cfx

# Ajustes sueltos, sin escribir un perfil (seccion.clave=valor)
python -m sqxtools.cli build-cfx --template v5.cfx -o v6.cfx \
  --settings "risk_reward.limit_slpt_rrr=true,entries.min_conditions=2"

# Perfiles de bloques: extraer, guardar, validar
python -m sqxtools.cli profile --from-sqb actual.sqb -o nas100.yaml
python -m sqxtools.cli profile --validate nas100.yaml --template BlockSettings.sqb

# Gestionar el cache de datos Parquet
python -m sqxtools.cli cache --list
python -m sqxtools.cli cache --clear
```

### Modificar la configuración del builder (`.cfx`)

A diferencia de los perfiles de `.sqb` (selección de bloques), un **perfil de builder**
cambia los *parámetros de configuración* de un `.cfx` existente — SL/PT, condiciones de
entrada, filtros horarios, rankings, probabilidades de salida **y qué bloques usa** —
preservando intacto todo lo demás (recursos, databanks).

Secciones del perfil: `risk_reward`, `entries`, `trading`, `rankings`, `exits`, `blocks`.
Ver `perfiles/README.md` para la diferencia entre los dos tipos de perfil.

#### Activar bloques desde el `.cfx` (crítico)

**El `.sqb` es el catálogo global; el `.cfx` lleva su PROPIA selección de bloques, y es la
que el builder usa en un build.** Activar una señal solo en el `.sqb` no tiene efecto.

```yaml
blocks:
  add_signals: [StochSlowDCrossDown, VortexDowntrend]
  remove_indicators: [Indicators.RSI]
  set_signals: [RSIFalling, ADXHigher]   # lista exacta: activa estas y desactiva el resto
```

Los nombres se validan contra el catálogo del propio `.cfx`; si no existen, el comando
aborta con una sugerencia de corrección.

```bash
python -m sqxtools.cli build-cfx --template v5.cfx \
  --profile perfiles/builder-nas100-winrate.yaml -o output/v6.cfx

# Ajustes sueltos sin perfil
python -m sqxtools.cli build-cfx --template v5.cfx -o v6.cfx \
  --settings "risk_reward.limit_slpt_rrr=true,risk_reward.rrr_from=60,entries.min_conditions=3"
```

Secciones del perfil: `risk_reward`, `entries`, `trading`, `rankings`, `exits`.
Las claves desconocidas se reportan como advertencia en vez de ignorarse en silencio.

### Perfiles de bloques

Un perfil es un archivo YAML o JSON con la selección de bloques, reutilizable:

```yaml
name: nas100-shorts
signals:
  - SuperTrendDownTrend
  - IsDowntrend
  - RSIFalling
indicators:
  - Indicators.RSI
  - Prices.Close
  - IsGreater
stopLimitBlocks:
  - Stop/Limit Price Ranges.ATR
order_types:
  - EnterAtStop
exit_types:
  - StopLoss.StopLoss
```

> **Importante:** `build-sqb` usa el `.sqb` origen como plantilla y conserva todos los
> bloques con su firma exacta de parámetros. StrategyQuant **valida esa firma**: si un
> bloque tiene un parámetro que no existe en su definición (p. ej. `#Level#` en
> `RSIFalling`), SQ **no lo marca**. Nunca construyas bloques con parámetros inventados.
>
> **Campos omitidos = sin cambios.** Si no pasás `--order-types`, esos bloques conservan
> su estado original en el `.sqb`. Pasá una lista vacía para desactivarlos explícitamente.

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
│   ├── parser.py           # Parser de .cfx (XML → modelo)
│   ├── sqb_parser.py       # Parser de .sqb (Block Settings)
│   ├── sqb_builder.py      # Generador de .sqb recomendado (usa el catálogo origen)
│   ├── cfx_builder.py      # Aplica perfiles de configuración sobre un .cfx
│   ├── models.py           # Dataclasses del modelo
│   ├── analyzer.py         # Resumen ejecutivo
│   ├── compare.py          # Comparador de configs
│   ├── serializer.py       # JSON / Markdown / YAML
│   ├── ai_analyzer.py      # Prompt de sistema para el análisis con IA
│   ├── data_downloader.py  # Descarga Dukascopy / Yahoo (Parquet + cache incremental)
│   ├── edge_analyzer.py    # Análisis de mercado y propuestas de builder
│   ├── date_optimizer.py   # Optimizador de rangos IS/OOS
│   ├── cli.py              # Interfaz CLI
│   └── tests/
│       ├── test_parser.py      # Tests del parser .cfx
│       ├── test_sqb.py         # Tests de .sqb (parser, builder, validación, diff, perfiles)
│       ├── test_cfx_builder.py # Tests del patcher de .cfx
│       ├── test_real_files.py  # Tests con .cfx reales
│       ├── conftest.py
│       └── fixtures/           # .cfx de ejemplo
├── perfiles/               # perfiles reutilizables (ver perfiles/README.md)
│   ├── README.md               # ← diferencia entre perfil de bloques y de builder
│   ├── nas100-shorts.yaml      # bloques: selección base (22 bloques)
│   ├── blocks-nas100-robustez.yaml  # bloques: 15 señales + indicadores + stops
│   ├── builder-nas100-winrate.yaml  # builder: subir win/loss ratio (RRR 60-120)
│   ├── builder-nas100-moretrades.yaml   # builder: más trades
│   └── builder-nas100-robustez.yaml     # builder: robustez estadística
├── analisis/               # razonamiento de las optimizaciones
│   └── v5-optimizacion-winloss.md
├── README.md
├── .gitignore
└── setup.py
```

## Licencia

MIT
