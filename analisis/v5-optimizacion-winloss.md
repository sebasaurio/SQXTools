# Optimización v5 → mejor Win/Loss Ratio (NAS100 short-only, H1)

Análisis de `Build strategies 1 _ 5.cfx` + mercado real NAS100 (39.485 barras H1, 6,7 años, Dukascopy).

## Estado actual del v5

- **22 bloques activos** — 7 signals + 11 indicators/prices/operators + 4 stopLimitBlocks
- Short-only, NAS100 H1 Exness (spread 112), `RealisticGapsHandling=true`
- IS: 2018.06.27 → 2026.06.23 (8 años) · OOS: 4 rangos walk-forward → **válido**
- Build: genetic-evolution, población 150, 150 generaciones, 5 islas
- Fitness: `ReturnDDRatio` · Rankings activos: Ret/DD ≥ 1, Trades ≥ 100, PF ≥ 1.2, DD ≤ 12%

## El problema de fondo: el RRR manda sobre el win rate

Breakeven win rate = `1 / (1 + RRR)`

| RRR (PT/SL) | Win rate de breakeven |
|---|---|
| 0.8 : 1 | 55.6% |
| 1.0 : 1 | 50.0% |
| 1.5 : 1 | 40.0% |
| 2.0 : 1 | 33.3% |
| **3.0 : 1** | **25.0%** |

**Config actual:**
- SL ATR múltiplo: **1.5 – 2.5**
- PT ATR múltiplo: **2.0 – 4.5**
- `LimitSLPTRRR = false` → **sin techo de RRR**
- RRR resultante: **0.8 : 1 hasta 3.0 : 1** (típico ~1.6 : 1 → breakeven 38%)

Con fitness `ReturnDDRatio`, el genético **converge a RRR altos** (pocas pérdidas grandes,
muchas ganancias pequeñas = win rate bajo). El win/loss ratio hoy es un *subproducto*,
no algo que estés controlando.

---

## Cambios propuestos (por impacto)

### 🔴 1. Acotar el RRR — el cambio más importante

**SL/PT Options → `LimitSLPTRRR = true`**, rango `60 – 120`
(PT = 0.6× a 1.2× el SL → breakeven 45.5% – 62.5%)

Complementario — **bajar el PT ATR múltiplo de `2 – 4.5` a `1.2 – 2.0`**
→ RRR típico baja de 1.62 : 1 a ~0.80 : 1

Dejar el SL como está (1.5 – 2.5 ATR): si achicás el SL para subir el RRR volvés al problema.

### 🔴 2. Activar el filtro de sesión (ya lo tenés configurado, pero apagado)

`LimitTimeRange = false` → los valores `SignalTimeRangeFrom=30600 / To=54000`
(**08:30 – 15:00 UTC**) **no tienen efecto**.

**Acción:** `LimitTimeRange = true` con ventana **12:00 – 20:00 UTC** (`43200` – `72000`).

> **CORRECCIÓN (importante).** Una versión anterior de este documento proponía
> aislar 12:00–15:00 UTC por ser "las mejores horas para shorts". **Eso estaba mal
> fundado.** Al medirlo con rigurosidad:
>
> - El **sesgo direccional por hora no es estadísticamente significativo**: de las 24
>   horas, solo 1 supera p<0.05 (y es la hora 6, con sesgo *alcista*). Es exactamente
>   lo esperable por azar — es decir, **ruido**. La hora 14, que se citaba como "mejor
>   para shorts", tiene p=0.40.
> - Peor: la ventana 12–15 incluía las horas **13 y 15**, que son las dos **más
>   alcistas** del día en promedio (+0.0165%, +0.0157%).
> - Lo que **sí** es un patrón robusto es la **volatilidad**:
>
> | Ventana | Rango medio | % del día |
> |---|---|---|
> | Asia 00–08 UTC | 0.241% | 35.0% |
> | 12–15 UTC (propuesta anterior) | 0.612% | **17.5%** |
> | **12–20 UTC (propuesta)** | **0.543%** | **38.9%** |
> | 00–23 UTC (sin filtro) | 0.369% | 100% |
>
> La ventana ampliada conserva el **89% de la volatilidad** de la estrecha pero con
> **2,2× más oportunidades**. Filtrar por dirección era perseguir ruido; filtrar por
> volatilidad excluye las horas muertas (00–07 y 21–23 UTC) sin sacrificar trades.

### 🔴 3. Endurecer las condiciones de entrada

`minConditions = 1`, `maxConditions = 2` → entradas con **una sola** confirmación.

- **Acción:** `minConditions = 3`
- Con 7 señales activas, exigir 3 confirmaciones simultáneas descarta las entradas
  marginales. Es el segundo mayor impulsor del win rate después del RRR.

### 🟡 4. Rankings: agregar el win rate como filtro

Hoy: `Ret/DD ≥ 1`, `Trades ≥ 100`, `PF ≥ 1.2`, `DD ≤ 12%`

- **Subir `ProfitFactor` de `1.2` a `1.45`**
- **Agregar condición `WinLossRatio ≥ 1.5`** (o `PercentProfitable ≥ 45%`)
- Considerar cambiar el fitness de `ReturnDDRatio` a `SharpeRatio` o `ProfitFactor`:
  `ReturnDDRatio` premia RRR alto y es **anti-correlacionado** con el win rate.
  Si querés win rate, el fitness tiene que dejar de premiar lo contrario.

### 🟡 5. Limitar el overtrading

- `MaxTradesPerDay = 0` (sin límite) → **poner 3**
- `PickerMaxOpenPositionsShort = 8` → **bajar a 2** (8 shorts simultáneos en NAS100 = riesgo de correlación)
- `DontTradeOnWeekends = false` → **poner true** (evita gap risk del domingo)

### 🟢 6. Revisar las salidas aleatorias

- `ExitAfterBars.ExitAfterBars` con probabilidad **50** → salir "N barras después" al azar
  degrada la lógica PT/SL y ensucia el win rate. **Bajar a 20 o desactivar.**
- `TrailingStop` y `MoveSL2BE` al 100%: manteneos, ayudan a cortar pérdidas.
- `ExitRules.ShortImprovement = add-or-replace` ya está activo — bien, aprovechalo con
  las condiciones nuevas.

---

## Config objetivo (resumen)

| Parámetro | Actual | Propuesto |
|---|---|---|
| `LimitSLPTRRR` | false | **true** |
| RRR range | — | **60 – 120** |
| PT ATR múltiplo | 2.0 – 4.5 | **1.2 – 2.0** |
| SL ATR múltiplo | 1.5 – 2.5 | 1.5 – 2.5 (sin cambio) |
| `LimitTimeRange` | **false** | **true** |
| Rango horario | 08:30 – 15:00 (inerte) | **12:00 – 20:00 UTC** |
| `minConditions` | 1 | **3** |
| `maxConditions` | 2 | 3 |
| `ProfitFactor` filtro | 1.2 | **1.45** |
| `WinLossRatio` filtro | — | **≥ 1.5** |
| Fitness | ReturnDDRatio | **SharpeRatio** (o PF) |
| `MaxTradesPerDay` | 0 | **3** |
| `MaxOpenPositionsShort` | 8 | **2** |
| `DontTradeOnWeekends` | false | **true** |
| `ExitAfterBars` prob | 50 | **20** |

**Win rate esperado:** con RRR ~0.8 : 1 y entradas filtradas (3 condiciones + ventana
líquida), el breakeven baja a ~55% y el genético empieza a seleccionar por win rate.
Sin acotar el RRR, ningún otro cambio mueve la aguja de verdad.

**Sobre el tamaño de la ventana:** no conviene achicarla más buscando "las mejores horas".
El sesgo direccional por hora no es significativo en NAS100, así que recortar la ventana
solo reduce el número de trades sin mejorar la calidad. Si se quiere ser más selectivo,
conviene hacerlo por **condiciones de entrada** (`minConditions`) o por **volatilidad
mínima**, no por hora del día.

## Validación: round-trip por StrategyQuant

Se cargó `output/v6_winrate.cfx` en StrategyQuant y se guardó como `Build strategies 3.cfx`.
Comparación XML completa (18.029 elementos):

**Sobrevivieron 19/19 ajustes**: RRR (60/120), PT ATR (1.2–2.0), SL ATR (1.5–2.5),
`LimitSLPTRRR`, `minConditions`/`maxConditions` (3/3), `LimitTimeRange` + horario
(43200–54000), `MaxTradesPerDay` (3), `DontTradeOnWeekends`, `PickerMaxOpenPositionsShort` (2),
`ExitOnFriday`, fitness `SharpeRatio` y `ProfitFactor ≥ 1.45`. Los 22 bloques intactos.

**2 valores revertidos:**

1. **`WinLossRatio ≥ 1.5` → 1.2.** Causa: la condición se había *creado desde cero* con
   atributos mínimos, y StrategyQuant la re-instancia desde la definición de la columna,
   reiniciando el valor al default. **Corregido**: ahora se *reutiliza una condición
   inactiva* existente (hay 9 slots libres), preservando la estructura completa de
   atributos. Las condiciones *existentes* que solo se modifican de valor nunca se
   resetean — solo pasaba con las creadas a mano.

2. **`ExitAfterBars` probability 20 → 50.** Efecto colateral del mismo patrón, pero
   StrategyQuant lo administra internamente para ese bloque (`type="int"`); el resto de
   los exit types (`type="formula"`) conservaron su valor. **Acción**: ajustarlo a mano
   en la UI de StrategyQuant (1 clic).

Cambios estructurales que hizo SQ por su cuenta (normales, no son problema):
`Symbols`/`InstrumentInfo` → `AllBrokers`, y reorganización de `Databanks`.

## Cómo medirlo

Después del próximo build, correr en StrategyQuant el ranking con la columna
`WinLossRatio` / `PercentProfitable` visible, y comparar contra el v5.
Si el win rate no sube, el RRR sigue siendo el culpable — revisá la distribución
de PT/SL que eligió el genético.
