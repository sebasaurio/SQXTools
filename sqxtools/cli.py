"""CLI de SQXTools — comandos de parseo, análisis y comparación."""

import argparse
import json
import sys
from pathlib import Path

from .parser import parse_cfx
from .serializer import save_output, to_json, to_markdown
from .analyzer import summarize, active_blocks_only, blocks_by_category
from .compare import compare_configs
from .ai_analyzer import get_system_prompt
from .data_downloader import download_dukascopy, download_yfinance, load_data, list_cache, clear_cache
from .edge_analyzer import analyze_market


def cmd_parse(args):
    """Parsea un .cfx y genera JSON/Markdown."""
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


def cmd_analyze(args):
    """Analiza un .cfx y genera resumen ejecutivo."""
    inp = Path(args.input)
    if not inp.exists():
        print(f"ERROR: no existe {inp}", file=sys.stderr)
        return 1

    cfg = parse_cfx(inp)
    summary = summarize(cfg)

    out = Path(args.output) if args.output else inp.with_suffix(".summary.json")
    if out.suffix.lower() == ".json":
        out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    else:
        # Markdown summary
        md = _summary_to_markdown(summary)
        out.write_text(md, encoding="utf-8")

    print(f"✓ Análisis de {inp.name} → {out}")
    print(f"  Tipo: {summary['type']} | Bloques activos: {summary['blocks_summary']['active']}/{summary['blocks_summary']['total']}")
    return 0


def cmd_filter(args):
    """Filtra bloques (activos, por categoría)."""
    inp = Path(args.input)
    if not inp.exists():
        print(f"ERROR: no existe {inp}", file=sys.stderr)
        return 1

    cfg = parse_cfx(inp)
    blocks = cfg.blocks.get("building_blocks", [])

    if args.active_only:
        blocks = [b for b in blocks if b.get("use")]
    if args.category:
        blocks = [b for b in blocks if b.get("category") == args.category]

    result = {
        "filename": cfg.filename,
        "filters": {"active_only": args.active_only, "category": args.category},
        "count": len(blocks),
        "blocks": blocks,
    }

    out = Path(args.output) if args.output else inp.with_suffix(".filtered.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"✓ {len(blocks)} bloques filtrados → {out}")
    return 0


def cmd_compare(args):
    """Compara dos archivos .cfx."""
    inp1 = Path(args.input1)
    inp2 = Path(args.input2)
    if not inp1.exists() or not inp2.exists():
        print("ERROR: uno de los archivos no existe", file=sys.stderr)
        return 1

    cfg1 = parse_cfx(inp1)
    cfg2 = parse_cfx(inp2)
    diff = compare_configs(cfg1, cfg2)

    out = Path(args.output) if args.output else Path("diff.json")
    out.write_text(json.dumps(diff, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"✓ Comparación → {out}")
    return 0


def cmd_list_categories(args):
    """Lista las categorías de bloques disponibles."""
    inp = Path(args.input)
    if not inp.exists():
        print(f"ERROR: no existe {inp}", file=sys.stderr)
        return 1

    cfg = parse_cfx(inp)
    blocks = cfg.blocks.get("building_blocks", [])
    categories = {}
    for b in blocks:
        cat = b.get("category", "uncategorized")
        if cat not in categories:
            categories[cat] = {"total": 0, "active": 0}
        categories[cat]["total"] += 1
        if b.get("use"):
            categories[cat]["active"] += 1

    print(f"\nCategorías en {inp.name}:")
    for cat, counts in sorted(categories.items(), key=lambda x: -x[1]["total"]):
        print(f"  {cat}: {counts['total']} total, {counts['active']} activos")
    return 0


def cmd_edge_finder(args):
    """Analiza mercado y propone builder óptimo."""
    print(f"Analizando {args.symbol} ({args.timeframe}, {args.period})...")
    print(f"  Fuente: {args.source}")
    
    # Descargar datos
    try:
        if args.source == "yfinance":
            data_path = download_yfinance(
                symbol=args.symbol,
                timeframe=args.timeframe,
                period=args.period,
            )
        elif args.source == "dukascopy":
            data_path = download_dukascopy(
                symbol=args.symbol,
                timeframe=args.timeframe.replace("m", "").replace("h", "H"),
                output_dir="./data",
            )
        else:
            print(f"ERROR: Fuente no soportada: {args.source}", file=sys.stderr)
            return 1
    except ImportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR descargando datos: {e}", file=sys.stderr)
        return 1
    
    # Cargar y analizar
    df = load_data(data_path)
    analysis = analyze_market(df, symbol=args.symbol, timeframe=args.timeframe)
    
    # Guardar resultado
    out = Path(args.output) if args.output else Path(f"edge_finder_{args.symbol}_{args.timeframe}.json")
    out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    # Mostrar resumen
    print(f"\n✓ Análisis de mercado completo → {out}")
    print(f"  Barras analizadas: {analysis['data_info']['total_bars']}")
    print(f"  Volatilidad promedio: {analysis['volatility']['avg_range_pct']:.3f}%")
    
    if analysis.get("sessions", {}).get("best_trading_hours"):
        print(f"  Mejores horas para shorts: {[h['hour'] for h in analysis['sessions']['best_trading_hours']]}")
    
    if analysis.get("builder_proposal", {}).get("signals"):
        print(f"  Señales propuestas: {analysis['builder_proposal']['signals']}")
    
    if analysis.get("builder_proposal", {}).get("risk"):
        risk = analysis["builder_proposal"]["risk"]
        print(f"  Risk: ${risk['fixed_amount']}/trade, {risk['drawdown_pct']}% drawdown")
    
    return 0


def cmd_ai_analyze(args):
    """Prepara el .cfx para análisis con IA (agente lo analiza directamente)."""
    inp = Path(args.input)
    if not inp.exists():
        print(f"ERROR: no existe {inp}", file=sys.stderr)
        return 1

    cfg = parse_cfx(inp)
    summary = summarize(cfg)

    out = Path(args.output) if args.output else inp.with_suffix(".ai_input.json")
    out.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    print(f"✓ Resumen generado → {out}")
    print(f"  Bloques activos: {summary['blocks_summary']['active']}/{summary['blocks_summary']['total']}")
    print(f"  Categorías: {list(summary.get('categories', {}).keys())}")
    print()
    print("PROMPT DE SISTEMA PARA EL ANÁLISIS:")
    print("=" * 50)
    from .ai_analyzer import get_system_prompt
    print(get_system_prompt())
    print("=" * 50)
    print()
    print(f"El resumen está en: {out}")
    print("Ahora el agente puede analizar este resumen directamente.")
    return 0


def _summary_to_markdown(summary: dict) -> str:
    """Convierte un resumen a Markdown legible."""
    lines = [
        f"# {summary['filename']}",
        f"**Tipo:** {summary['type']}  ",
        f"**Versión:** {summary.get('version', 'n/a')}",
        "",
    ]

    bs = summary.get("blocks_summary", {})
    lines.append("## Resumen de Bloques")
    lines.append(f"- **Total:** {bs.get('total', 0)}")
    lines.append(f"- **Activos:** {bs.get('active', 0)}")
    lines.append(f"- **Inactivos:** {bs.get('inactive', 0)}")
    lines.append("")

    cats = summary.get("categories", {})
    if cats:
        lines.append("### Categorías (activos)")
        for cat, count in sorted(cats.items(), key=lambda x: -x[1]):
            lines.append(f"- **{cat}:** {count}")
        lines.append("")

    indicators = summary.get("indicators", [])
    if indicators:
        lines.append(f"### Indicadores/Parámetros ({len(indicators)} únicos)")
        for ind in indicators[:30]:
            params_str = ", ".join(f"{p['name']}={p['value']}" for p in ind["params"])
            lines.append(f"- **{ind['name']}** ({ind['category']}) {params_str}")
        if len(indicators) > 30:
            lines.append(f"- ... y {len(indicators) - 30} más")
        lines.append("")

    data = summary.get("data", {})
    if data:
        lines.append("## Datos")
        lines.append(f"- **Setups:** {data.get('num_setups', 0)}")
        lines.append(f"- **Rangos OOS:** {data.get('out_of_sample_ranges', 0)}")
        charts = data.get("charts", [])
        for ch in charts:
            lines.append(f"- **{ch['symbol']}** ({ch['timeframe']}, spread={ch['spread']})")
        lines.append("")

    rankings = summary.get("rankings", {})
    if rankings:
        lines.append("## Rankings")
        lines.append(f"- **Tipo:** {rankings.get('type', '')}")
        lines.append(f"- **Fitness:** {rankings.get('fitness_criteria', '')}")
        lines.append(f"- **Condiciones activas:** {rankings.get('num_active_conditions', 0)}/{rankings.get('num_conditions', 0)}")
        for f in rankings.get("active_filters", []):
            lines.append(f"  - {f['left']} {f['comparator']} {f['right']}")
        lines.append("")

    cc = summary.get("cross_checks", {})
    if cc:
        lines.append("## Cross Checks")
        lines.append(f"- **Usa:** {cc.get('use', False)}")
        lines.append(f"- **Evalúa todo:** {cc.get('evaluate_all', False)}")
        for check in cc.get("enabled", []):
            lines.append(f"  - ✓ {check}")
        lines.append("")

    res = summary.get("resources", {})
    if res:
        lines.append("## Recursos")
        lines.append(f"- **Símbolos:** {', '.join(res.get('symbols', []))}")
        lines.append(f"- **Brokers:** {', '.join(res.get('brokers', []))}")
        lines.append("")

    return "\n".join(lines)


def cmd_cache(args):
    """Gestiona cache de datos."""
    if args.list:
        files = list_cache()
        if not files:
            print("No hay archivos en cache.")
            return 0
        print(f"\nArchivos en cache ({len(files)}):")
        for f in files:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.name} ({size_mb:.1f} MB)")
        return 0
    
    if args.clear:
        n = clear_cache()
        print(f"✓ {n} archivos eliminados de cache.")
        return 0
    
    print("Usa --list o --clear")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="sqxtools",
        description="Parser y analizador de .cfx de StrategyQuant — convierte configs en JSON legible para IA.",
    )
    sub = ap.add_subparsers(dest="command", help="Comando a ejecutar")

    # parse
    p_parse = sub.add_parser("parse", help="Parsea un .cfx a JSON/Markdown")
    p_parse.add_argument("input", help="Archivo .cfx de entrada")
    p_parse.add_argument("-o", "--output", help="Archivo de salida (.json o .md)")
    p_parse.add_argument("--type", choices=["building_config", "build", "retester", "optimizer", "custom_project", "info"], help="Forzar tipo")
    p_parse.set_defaults(func=cmd_parse)

    # analyze
    p_analyze = sub.add_parser("analyze", help="Genera resumen ejecutivo del .cfx")
    p_analyze.add_argument("input", help="Archivo .cfx")
    p_analyze.add_argument("-o", "--output", help="Salida (.json o .md)")
    p_analyze.set_defaults(func=cmd_analyze)

    # filter
    p_filter = sub.add_parser("filter", help="Filtra bloques (activos, por categoría)")
    p_filter.add_argument("input", help="Archivo .cfx")
    p_filter.add_argument("-o", "--output", help="Salida JSON")
    p_filter.add_argument("--active-only", action="store_true", help="Solo bloques activos")
    p_filter.add_argument("--category", help="Filtrar por categoría")
    p_filter.set_defaults(func=cmd_filter)

    # compare
    p_compare = sub.add_parser("compare", help="Compara dos .cfx")
    p_compare.add_argument("input1", help="Primer .cfx")
    p_compare.add_argument("input2", help="Segundo .cfx")
    p_compare.add_argument("-o", "--output", help="Salida JSON")
    p_compare.set_defaults(func=cmd_compare)

    # list-categories
    p_list = sub.add_parser("list-categories", help="Lista categorías de bloques")
    p_list.add_argument("input", help="Archivo .cfx")
    p_list.set_defaults(func=cmd_list_categories)

    # ai-analyze
    p_ai = sub.add_parser("ai-analyze", help="Prepara .cfx para análisis con IA")
    p_ai.add_argument("input", help="Archivo .cfx")
    p_ai.add_argument("-o", "--output", help="Salida JSON con resumen")
    p_ai.set_defaults(func=cmd_ai_analyze)

    # edge-finder
    p_edge = sub.add_parser("edge-finder", help="Analiza mercado y propone builder óptimo")
    p_edge.add_argument("--symbol", default="NQ=F", help="Símbolo (NQ=F, EURUSD, etc.)")
    p_edge.add_argument("--timeframe", default="60m", help="Temporalidad (1m, 5m, 15m, 60m, 1h)")
    p_edge.add_argument("--period", default="2y", help="Período de datos (1y, 2y, 5y)")
    p_edge.add_argument("--source", choices=["dukascopy", "yfinance"], default="yfinance", help="Fuente de datos")
    p_edge.add_argument("-o", "--output", help="Salida JSON")
    p_edge.set_defaults(func=cmd_edge_finder)

    # cache
    p_cache = sub.add_parser("cache", help="Gestiona cache de datos")
    p_cache.add_argument("--list", action="store_true", help="Lista archivos en cache")
    p_cache.add_argument("--clear", action="store_true", help="Elimina cache")
    p_cache.set_defaults(func=cmd_cache)

    args = ap.parse_args(argv)
    if not args.command:
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
