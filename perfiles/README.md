# Perfiles

Hay **dos tipos de perfil**, y confundirlos es el error más común:

| | Perfil de **bloques** (`build-sqb`) | Perfil de **builder** (`build-cfx`) |
|---|---|---|
| Aplica a | `.sqb` (catálogo global de bloques) | `.cfx` (config de un build) |
| Cambia | qué bloques están activos | SL/PT, entradas, horario, rankings, salidas **y bloques** |
| Salida | `.sqb` | `.cfx` |

> **El `.cfx` lleva su propia selección de bloques, y es la que el builder usa en un build.**
> Activar una señal solo en el `.sqb` **no tiene efecto** sobre el build. Si querés que el
> builder use señales nuevas, activalas en el `.cfx` (sección `blocks`) **y** generá el `.sqb`
> equivalente para que el catálogo global coincida.

## Perfiles de bloques (`.sqb`)

Claves: `signals`, `indicators`, `stopLimitBlocks`, `order_types`, `exit_types`
(+ `name`/`description`/`symbol`/`timeframe` opcionales). Un grupo ausente **no se toca**.

```bash
python -m sqxtools.cli build-sqb --template BlockSettings.sqb \
  --profile perfiles/blocks-nas100-robustez.yaml -o output/BlockSettings_robustez.sqb
```

## Perfiles de builder (`.cfx`)

Secciones:

| Sección | Controla |
|---|---|
| `risk_reward` | RRR (`limit_slpt_rrr`, `rrr_from`/`rrr_to`), múltiplos ATR de SL y PT |
| `entries` | `min_conditions` / `max_conditions` (complejidad de las reglas) |
| `trading` | ventana horaria, `max_trades_per_day`, posiciones simultáneas, fin de semana |
| `rankings` | `fitness` y filtros de calidad (`profit_factor_min`, `win_loss_ratio_min`, …) |
| `exits` | probabilidades de los tipos de salida |
| `blocks` | `add_*` / `remove_*` / `set_signals` sobre el `.cfx` |

```bash
python -m sqxtools.cli build-cfx --template v5.cfx \
  --profile perfiles/builder-nas100-winrate.yaml -o output/v6_winrate.cfx
```

Las claves desconocidas se reportan como advertencia (no se ignoran en silencio).
Los nombres de bloque inválidos **abortan** el comando con una sugerencia.

## Perfiles incluidos

| Archivo | Tipo | Objetivo |
|---|---|---|
| `nas100-shorts.yaml` | bloques | Selección base NAS100 short-only (22 bloques) |
| `blocks-nas100-robustez.yaml` | bloques | 15 señales de familias diversas + indicadores + stops (30 bloques) |
| `builder-nas100-winrate.yaml` | builder | Subir win/loss ratio acotando el RRR (60–120) |
| `builder-nas100-moretrades.yaml` | builder | Más trades relajando oportunidad, no calidad |
| `builder-nas100-robustez.yaml` | builder | Muchos trades con calidad intacta, métricas confiables |

Razonamiento completo de los tres perfiles de builder en
[`analisis/v5-optimizacion-winloss.md`](../analisis/v5-optimizacion-winloss.md).
