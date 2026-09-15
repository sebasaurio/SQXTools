"""Round-trip verifier: garantiza que lo que generaste es lo que SQX va a correr.

SQ a veces revierte valores al re-instanciar configs (histórico: condiciones de rankings
creadas a mano, ExitAfterBars probability). El verifier compara TRES puntos:

  base        el .cfx de origen (antes de tus cambios)
  generated   el .cfx que generaste con build-cfx
  saved       el .cfx que SQ guardó después de que lo cargaste

Un setting está:
  - OK          generated == saved (sobrevivió el round-trip)
  - REVERTED    generated != base  y  saved == base (SQ lo volvió al valor original)
  - CHANGED     los tres difieren (SQ lo cambió por su cuenta — normalmente estructural)
"""
from __future__ import annotations

from pathlib import Path

from .parser import parse_cfx


def _trading_map(cfg) -> dict[str, object]:
    s = cfg.settings or {}
    return {p["key"]: p.get("value") for p in (s.get("trading_options") or [])
            if isinstance(p, dict) and "key" in p}


def _slpt_map(cfg) -> dict[str, object]:
    return (cfg.what_to_build or {}).get("slpt_options") or {}


def _rankings_active(cfg) -> dict[str, tuple[str, object]]:
    out = {}
    for f in (getattr(cfg, "rankings", None) or {}).get("conditions") or []:
        if not f.get("use"):
            continue
        left = (f.get("left_side") or {}).get("column", {}).get("column", "")
        val = (f.get("right_side") or {}).get("numeric")
        if left and val is not None:
            out[f"{left}@{f.get('comparator','>=').replace('>','gt').replace('<','lt').replace('=','e')}"] = \
                (f.get("comparator", ">="), val)
    return out


def _fitness(cfg):
    return (getattr(cfg, "rankings", None) or {}).get("fitness_criteria")


def _exit_probs(cfg) -> dict[str, object]:
    """Probabilidades de exit types (use/probability por bloque)."""
    out = {}
    for b in (cfg.blocks or {}).get("exit_types", []) or []:
        if isinstance(b, dict):
            out[b.get("key", "?")] = {
                "use": b.get("use"),
                "probability": b.get("probability"),
            }
    return out


def _collect(cfg) -> dict:
    return {
        "trading": _trading_map(cfg),
        "slpt": _slpt_map(cfg),
        "rankings_conditions": _rankings_active(cfg),
        "fitness": _fitness(cfg),
        "exit_types": _exit_probs(cfg),
    }


_INTERESTING = {  # settings de trading que reportamos individualmente
    "LimitTimeRange", "SignalTimeRangeFrom", "SignalTimeRangeTo",
    "MaxTradesPerDay", "DontTradeOnWeekends", "ExitOnFriday", "FridayExitTime",
    "PickerMaxOpenPositionsShort", "PickerMaxOpenPositionsLong", "RealisticGapsHandling",
}


def verify_round_trip(base_path: str | Path, generated_path: str | Path,
                      saved_path: str | Path) -> str:
    base = _collect(parse_cfx(base_path))
    gen = _collect(parse_cfx(generated_path))
    saved = _collect(parse_cfx(saved_path))

    L: list[str] = ["# Round-trip: generado → SQ → guardado", ""]
    n_ok = n_rev = n_chg = 0
    reverted: list[str] = []

    # settings de trading
    for key in sorted(_INTERESTING):
        g, s = gen["trading"].get(key), saved["trading"].get(key)
        if g == s:
            continue
        if s == base["trading"].get(key):
            n_rev += 1
            reverted.append(f"trading.{key}: generaste {g!r} → SQ volvió a {s!r}")
        else:
            n_chg += 1
            L.append(f"- 🟡 trading.{key}: generado {g!r} → guardado {s!r} (SQ lo cambió)")

    # SLPT
    for key in sorted(set(gen["slpt"]) | set(saved["slpt"])):
        g, s = gen["slpt"].get(key), saved["slpt"].get(key)
        if g == s or key not in ("LimitSLPTRRR", "LimitSLPTRRRFrom", "LimitSLPTRRRTo",
                                 "MinSLATRMultiple", "MaxSLATRMultiple", "MinPTATRMultiple",
                                 "MaxPTATRMultiple", "MinSLInPips", "MinPTInPips"):
            continue
        if s == base["slpt"].get(key):
            n_rev += 1
            reverted.append(f"slpt.{key}: generaste {g!r} → SQ volvió a {s!r}")
        else:
            n_chg += 1
            L.append(f"- 🟡 slpt.{key}: generado {g!r} → guardado {s!r}")

    # condiciones de rankings activas
    gen_r, saved_r, base_r = gen["rankings_conditions"], saved["rankings_conditions"], base["rankings_conditions"]
    for key in sorted(set(gen_r) | set(saved_r)):
        g, s = gen_r.get(key), saved_r.get(key)
        if g == s:
            continue
        if key not in saved_r:
            n_rev += 1
            reverted.append(f"ranking {key}: generaste {g} → SQ la desactivó/eliminó")
        elif s == base_r.get(key):
            n_rev += 1
            reverted.append(f"ranking {key}: generaste {g} → SQ volvió a {s}")
        else:
            n_chg += 1
            L.append(f"- 🟡 ranking {key}: generado {g} → guardado {s}")

    # fitness
    if gen["fitness"] != saved["fitness"]:
        if saved["fitness"] == base["fitness"]:
            n_rev += 1
            reverted.append(f"fitness: generaste {gen['fitness']!r} → SQ volvió a {saved['fitness']!r}")
        else:
            n_chg += 1
            L.append(f"- 🟡 fitness: {gen['fitness']!r} → {saved['fitness']!r}")

    # exit types (probabilidades)
    for key in sorted(set(gen["exit_types"]) | set(saved["exit_types"])):
        g, s = gen["exit_types"].get(key), saved["exit_types"].get(key)
        if g == s:
            continue
        if s == base["exit_types"].get(key):
            n_rev += 1
            reverted.append(f"exit {key}: generaste {g} → SQ volvió a {s}")
        else:
            n_chg += 1
            L.append(f"- 🟡 exit {key}: generado {g} → guardado {s}")

    # settings que coinciden (resumen)
    common = sum(1 for k in _INTERESTING if gen["trading"].get(k) == saved["trading"].get(k)
                 and gen["trading"].get(k) is not None)
    n_ok = common

    L.append("")
    if reverted:
        L.append(f"## ⚠️ Revertidos por SQ ({n_rev})")
        L.extend(f"- {r}" for r in reverted)
        L.append("")
        L.append("Causa histórica: SQ re-instancia condiciones creadas desde cero con atributos "
                 "mínimos y las resetea al default. Reutilizar slots inactivos existentes lo evita.")
    L.append(f"## Resumen: {n_ok} settings OK · {n_rev} revertidos · {n_chg} cambiados por SQ")
    if not reverted and n_chg == 0:
        L.append("✅ Round-trip limpio: lo que generaste es lo que va a correr.")
    return "\n".join(L)
