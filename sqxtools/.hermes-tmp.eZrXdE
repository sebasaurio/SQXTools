"""CLI de SQXTools."""

import argparse
import sys
from pathlib import Path

from .parser import parse_cfx
from .serializer import save_output


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="sqxtools",
        description="Convierte archivos .cfx de StrategyQuant en JSON/Markdown legible para IA.",
    )
    ap.add_argument("input", help="Archivo .cfx de entrada")
    ap.add_argument(
        "-o", "--output",
        help="Archivo de salida (.json o .md). Por defecto: <input>.json",
    )
    ap.add_argument(
        "--type",
        choices=["building_config", "build", "retester", "optimizer", "custom_project", "info"],
        help="Forzar tipo de config (si no se infiere bien)",
    )
    args = ap.parse_args(argv)

    inp = Path(args.input)
    if not inp.exists():
        print(f"ERROR: no existe {inp}", file=sys.stderr)
        return 1

    cfg = parse_cfx(inp)
    if args.type:
        from .models import CfxType
        cfg.cfx_type = CfxType(args.type)

    out = Path(args.output) if args.output else inp.with_suffix(".json")
    save_output(cfg, out)
    print(f"✓ {inp.name} → {out} (tipo: {cfg.cfx_type.value})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
