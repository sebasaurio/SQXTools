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

- Mejor hora para shorts en NAS100: **14 UTC** (retorno promedio −0.0105%, rango 0.758%)
- Horas más bajistas: 14, 11, 0 UTC
- **Acción:** `LimitTimeRange = true`
- **Afinar a 12:00 – 15:00 UTC** (`43200` – `54000`) → solo las 3 horas de mayor volatilidad
  y sesgo bajista. Filtrar las horas flojas sube el win rate directamente.

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
| Rango horario | 08:30 – 15:00 (inerte) | **12:00 – 15:00 UTC** |
| `minConditions` | 1 | **3** |
| `maxConditions` | 2 | 3 |
| `ProfitFactor` filtro | 1.2 | **1.45** |
| `WinLossRatio` filtro | — | **≥ 1.5** |
| Fitness | ReturnDDRatio | **SharpeRatio** (o PF) |
| `MaxTradesPerDay` | 0 | **3** |
| `MaxOpenPositionsShort` | 8 | **2** |
| `DontTradeOnWeekends` | false | **true** |
| `ExitAfterBars` prob | 50 | **20** |

**Win rate esperado:** con RRR ~0.8 : 1 y entradas filtradas (3 condiciones + sesión),
el breakeven baja a ~55% y el genético empieza a seleccionar por win rate.
Sin acotar el RRR, ningún otro cambio mueve la aguja de verdad.

## Cómo medirlo

Después del próximo build, correr en StrategyQuant el ranking con la columna
`WinLossRatio` / `PercentProfitable` visible, y comparar contra el v5.
Si el win rate no sube, el RRR sigue siendo el culpable — revisá la distribución
de PT/SL que eligió el genético.
