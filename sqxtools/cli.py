"""CLI de SQXTools — comandos de parseo, análisis y comparación."""

import argparse
import json
import sys
from pathlib import Path

from .parser import parse_cfx
from .serializer import save_output
from .analyzer import summarize
from .compare import compare_configs
from .data_downloader import download_dukascopy, download_yfinance, load_data, list_cache, clear_cache
from .edge_analyzer import analyze_market
from .date_optimizer import optimize_date_ranges
from .sqb_builder import build_recommended_sqb, get_block_definition, dump_catalog


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
    print(f"  Barras analizadas: {analysis.get('data_info', {}).get('total_bars', 'n/a')}")

    vol = analysis.get("volatility", {}).get("avg_range_pct")
    if vol is not None:
        print(f"  Volatilidad promedio: {vol:.3f}%")

    hours = analysis.get("sessions", {}).get("best_trading_hours") or []
    if hours:
        print(f"  Mejores horas para shorts: {[h.get('hour') for h in hours]}")

    proposal = analysis.get("builder_proposal", {})
    if proposal.get("signals"):
        print(f"  Señales propuestas: {[s.get('name') for s in proposal['signals']]}")

    risk = proposal.get("risk")
    if risk:
        print(f"  Risk: ${risk.get('fixed_amount')}/trade, {risk.get('drawdown_pct')}% drawdown")

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



def cmd_full_analysis(args):
    """Análisis completo: mercado + builder + propuestas de mejora."""
    from .analyzer import summarize
    from .parser import parse_cfx
    from .edge_analyzer import analyze_market
    from .date_optimizer import optimize_date_ranges
    from .data_downloader import download_dukascopy, download_yfinance, load_data
    
    print(f"=== ANÁLISIS COMPLETO: {args.symbol} ({args.timeframe}) ===")
    print(f"  Fuente: {args.source}")
    if args.cfx:
        print(f"  Builder actual: {args.cfx}")
    print()
    
    # Paso 1: Descargar datos de mercado
    print("1. Descargando datos de mercado...")
    try:
        if args.source == "dukascopy":
            tf = args.timeframe.replace("m", "").replace("h", "H")
            data_path = download_dukascopy(symbol=args.symbol, timeframe=tf)
        else:
            tf = args.timeframe.replace("H", "h").replace("M", "m").lower()
            data_path = download_yfinance(symbol=args.symbol, timeframe=tf, period="2y")
    except ImportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR descargando: {e}", file=sys.stderr)
        return 1
    
    df = load_data(data_path)
    print(f"   ✓ {len(df)} barras cargadas")
    
    # Paso 2: Analizar mercado (Edge Finder)
    print("2. Analizando mercado (Edge Finder)...")
    edge = analyze_market(df, symbol=args.symbol, timeframe=args.timeframe)
    print(f"   ✓ Volatilidad: {edge['volatility']['avg_range_pct']:.3f}%")
    print(f"   ✓ Mejor hora: {[h['hour'] for h in edge['sessions'].get('best_trading_hours', [])]}")
    
    # Paso 3: Optimizar fechas IS/OOS
    print("3. Optimizando fechas IS/OOS...")
    dates = optimize_date_ranges(df)
    print(f"   ✓ Regímenes: {len(dates['regimes'])}")
    print(f"   ✓ Propuestas: {len(dates['proposals'])}")
    rec = dates.get('recommendation', {})
    if rec.get('strategy') != 'insufficient_data':
        print(f"   ✓ Estrategia: {rec['strategy']} (IS: {rec.get('optimal_is_years', 0)}a, OOS: {rec.get('optimal_oos_years', 0)}a)")
    
    # Paso 4: Analizar builder actual (si se proporciona)
    builder_analysis = None
    if args.cfx:
        print("4. Analizando builder actual...")
        try:
            cfg = parse_cfx(args.cfx)
            builder_summary = summarize(cfg)
            builder_analysis = builder_summary
            print(f"   ✓ Bloques activos: {builder_summary['blocks_summary']['active']}/{builder_summary['blocks_summary']['total']}")
            print(f"   ✓ Señales: {len(builder_summary.get('indicators', []))}")
        except Exception as e:
            print(f"   ⚠ Error analizando .cfx: {e}")
    
    # Paso 5: Generar propuesta combinada
    print("5. Generando propuesta combinada...")
    proposal = _generate_full_proposal(edge, dates, builder_analysis)
    
    # Guardar resultado
    result = {
        "symbol": args.symbol,
        "timeframe": args.timeframe,
        "edge_finder": edge,
        "date_optimizer": dates,
        "builder_analysis": builder_analysis,
        "proposal": proposal,
    }
    
    out = Path(args.output) if args.output else Path(f"full_analysis_{args.symbol}.json")
    out.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    print()
    print("=" * 60)
    print(f"✓ Análisis completo → {out}")
    print()
    print("=== PROPUESTA OPTIMIZADA ===")
    p = proposal
    print(f"  Strategy: {p['strategy_type']} / {p['market_sides']}")
    if p.get('in_sample'):
        print(f"  IS: {p['in_sample']['from']} → {p['in_sample']['to']}")
    if p.get('out_of_sample_ranges'):
        for r in p['out_of_sample_ranges']:
            print(f"  OOS: {r['from']} → {r['to']}")
    if p.get('sessions'):
        print(f"  Sesiones: {p['sessions']}")
    
    # Mostrar building blocks organizados por categoría
    bb = p.get('building_blocks', {})
    if bb:
        for cat, blocks in bb.items():
            if blocks:
                print(f"  {cat.upper()} ({len(blocks)}):")
                for b in blocks:
                    name = b.get('name', '')
                    reason = b.get('reason', '')
                    params = b.get('params', {})
                    if params:
                        param_str = ', '.join(f"{k}={v}" for k, v in params.items() if v)
                        print(f"    - {name}: {param_str}")
                    else:
                        print(f"    - {name}: {reason}")
    
    if p.get('risk'):
        print(f"  Risk: ${p['risk'].get('fixed_amount', 0)}/trade, {p['risk'].get('drawdown_pct', 0)}% DD")
    if p.get('improvements'):
        print()
        print("  MEJORAS PROPUESTAS:")
        for imp in p['improvements']:
            print(f"    - {imp}")
    
    return 0


def _generate_full_proposal(edge: dict, dates: dict, builder: dict | None) -> dict:
    """Genera propuesta optimizada combinando edge finder, date optimizer y builder analysis."""
    proposal = {
        "strategy_type": "simple",
        "market_sides": edge.get("builder_proposal", {}).get("market_sides", "short"),
        "in_sample": None,
        "out_of_sample_ranges": [],
        "sessions": edge.get("builder_proposal", {}).get("sessions", []),
        "building_blocks": {
            "signals": [],
            "indicators": [],
            "stopLimitBlocks": [],
        },
        "risk": edge.get("builder_proposal", {}).get("risk", {}),
        "improvements": [],
    }
    
    # === Fechas IS/OOS ===
    date_proposals = dates.get("proposals", [])
    
    # Preferir walk-forward si está disponible
    wf_proposal = next((p for p in date_proposals if "Walk-Forward" in p.get("name", "")), None)
    split_proposal = next((p for p in date_proposals if "Split Simple" in p.get("name", "")), None)
    
    if wf_proposal:
        proposal["in_sample"] = wf_proposal.get("in_sample")
        proposal["out_of_sample_ranges"] = wf_proposal.get("out_of_sample_ranges", [])
    elif split_proposal:
        proposal["in_sample"] = split_proposal.get("in_sample")
        proposal["out_of_sample_ranges"] = [split_proposal.get("out_of_sample", {})]
    
    # === Building blocks propuestos por Edge Finder (organizados) ===
    edge_blocks = edge.get("builder_proposal", {}).get("building_blocks", {})
    for cat, blocks in edge_blocks.items():
        for b in blocks:
            proposal["building_blocks"][cat].append(b)
    
    # === Mejoras respecto al builder actual ===
    if builder:
        current_signals = set(i["name"] for i in builder.get("indicators", []))
        # Combinar todas las señales propuestas de todas las categorías
        proposed_signals = set()
        for cat, blocks in proposal.get("building_blocks", {}).items():
            for b in blocks:
                proposed_signals.add(b.get("name", ""))
        
        # Señales nuevas recomendadas
        new_signals = proposed_signals - current_signals
        for s in new_signals:
            proposal["improvements"].append(f"Añadir señal: {s}")
        
        # Señales redundantes en el builder
        redundant = current_signals - proposed_signals
        for s in redundant:
            proposal["improvements"].append(f"Evaluar remover: {s} (no recomendado por análisis de mercado)")
        
        # Comparar risk
        current_risk = builder.get("risk_money_management", {})
        proposed_risk = proposal.get("risk", {})
        if current_risk and proposed_risk:
            current_dd = current_risk.get("risk_management", {}).get("maxDrawdown", "0")
            proposed_dd = proposed_risk.get("drawdown_pct", 0)
            if current_dd and int(current_dd) > proposed_dd:
                proposal["improvements"].append(f"Reducir drawdown de {current_dd}% a {proposed_dd}%")
        
        # Comparar SLPT
        current_slpt = builder.get("what_to_build", {}).get("slpt_options", {})
        if current_slpt.get("SLRequired") and not current_slpt.get("SLATR"):
            proposal["improvements"].append("Cambiar SL a ATR-based para mejor adaptación")
        if current_slpt.get("PTRequired") and not current_slpt.get("PTATR"):
            proposal["improvements"].append("Cambiar PT a ATR-based para mejor adaptación")
    else:
        proposal["improvements"].append("Crear nuevo builder con configuración propuesta")
    
    # Añadir recomendaciones de fecha si hay régimen de alta volatilidad
    high_vol = [r for r in dates.get("regimes", []) if r.get("type") == "high_vol"]
    if high_vol:
        proposal["improvements"].append(f"Incluir al menos un período de alta volatilidad en OOS ({len(high_vol)} detectados)")
    
    return proposal



def cmd_build_sqb(args):
    """Genera un .sqb recomendado a partir del catálogo de bloques origen."""
    template = Path(args.template)
    if not template.exists():
        print(f"ERROR: no existe {template}", file=sys.stderr)
        return 1

    # Parsear listas separadas por coma
    def parse_list(s):
        if not s:
            return []
        return [x.strip() for x in s.split(",") if x.strip()]

    signals = parse_list(args.signals)
    indicators = parse_list(args.indicators)
    stops = parse_list(args.stops)
    ot = parse_list(args.order_types)
    et = parse_list(args.exit_types)

    report = build_recommended_sqb(
        template_path=template,
        output_path=args.output or "output/recommended.sqb",
        use_signals=signals,
        use_indicators=indicators,
        use_stops=stops,
        use_order_types=ot,
        use_exit_types=et,
    )

    print(f"✓ .sqb generado → {report['output']}")
    print()
    print(f"  Activados {sum(len(v) for v in report['activated'].values())} bloques:")
    for cat, blocks in report["activated"].items():
        print(f"    {cat} ({len(blocks)}): {', '.join(blocks)}")

    nf = {k: v for k, v in report["not_found"].items() if v}
    if nf:
        print()
        print("  ⚠ NO ENCONTRADOS en el catálogo:")
        for cat, keys in nf.items():
            if keys:
                print(f"    {cat}: {', '.join(keys)}")

    print()
    print(f"  OrderTypes activos: {[o['key'] for o in report['order_types']]}")
    print(f"  ExitTypes activos: {[e['key'] for e in report['exit_types']]}")
    return 0


def cmd_catalog(args):
    """Lista el catálogo de bloques disponibles con sus parámetros."""
    template = Path(args.template)
    if not template.exists():
        print(f"ERROR: no existe {template}", file=sys.stderr)
        return 1

    if args.block:
        d = get_block_definition(template, args.block)
        if not d:
            print(f"ERROR: bloque '{args.block}' no existe en el catálogo", file=sys.stderr)
            return 1
        print(f"Bloque: {d['key']}")
        print(f"  Categoría: {d['category']}")
        print("  Parámetros:")
        for p in d["params"]:
            extra = f" values={p['values']}" if p.get("values") else ""
            print(f"    {p['key']} ({p['type']}){extra}")
        if d.get("example_defaults"):
            print(f"  Valores por defecto: {d['example_defaults']}")
        return 0

    cat = dump_catalog(template, category=args.category)
    print(f"Catálogo: {len(cat)} bloques" + (f" en categoría '{args.category}'" if args.category else ""))
    for b in cat:
        params = ", ".join(p["key"] for p in b["params"])
        print(f"  [{b['category']}] {b['key']}: {params}")
    return 0


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


    # full-analysis: Edge Finder + Date Optimizer + AI Analyzer combinados
    p_full = sub.add_parser("full-analysis", help="Análisis completo: mercado + builder + propuestas")
    p_full.add_argument("--symbol", default="NAS100", help="Símbolo")
    p_full.add_argument("--timeframe", default="H1", help="Temporalidad")
    p_full.add_argument("--source", choices=["dukascopy", "yfinance"], default="dukascopy", help="Fuente")
    p_full.add_argument("--cfx", help="Archivo .cfx actual para comparar (opcional)")
    p_full.add_argument("-o", "--output", help="Salida JSON")
    p_full.set_defaults(func=cmd_full_analysis)


    # build-sqb
    p_build = sub.add_parser("build-sqb", help="Genera .sqb recomendado desde catálogo")
    p_build.add_argument("--template", required=True, help=".sqb origen con catálogo completo")
    p_build.add_argument("-o", "--output", help="Salida .sqb")
    p_build.add_argument("--signals", help="Señales separadas por coma")
    p_build.add_argument("--indicators", help="Indicadores separados por coma")
    p_build.add_argument("--stops", help="Stop/Limit blocks separados por coma")
    p_build.add_argument("--order-types", help="OrderTypes separados por coma")
    p_build.add_argument("--exit-types", help="ExitTypes separados por coma")
    p_build.set_defaults(func=cmd_build_sqb)

    # catalog
    p_cat = sub.add_parser("catalog", help="Lista catálogo de bloques y sus parámetros")
    p_cat.add_argument("--template", required=True, help=".sqb origen con catálogo completo")
    p_cat.add_argument("--category", choices=["signals", "indicators", "stopLimitBlocks"], help="Filtrar por categoría")
    p_cat.add_argument("--block", help="Detalle de un bloque específico")
    p_cat.set_defaults(func=cmd_catalog)

    # cache
    p_cache = sub.add_parser("cache", help="Gestiona cache de datos")
    p_cache.add_argument("--list", action="store_true", help="Lista archivos en cache")
    p_cache.add_argument("--clear", action="store_true", help="Elimina cache")
    p_cache.set_defaults(func=cmd_cache)


    # date-optimizer
    p_dates = sub.add_parser("date-optimizer", help="Optimiza rangos IS/OOS basados en datos históricos")
    p_dates.add_argument("--symbol", default="NQ=F", help="Símbolo")
    p_dates.add_argument("--timeframe", default="60m", help="Temporalidad")
    p_dates.add_argument("--period", default="2y", help="Período")
    p_dates.add_argument("--source", choices=["dukascopy", "yfinance"], default="yfinance", help="Fuente")
    p_dates.add_argument("--is-ratio", type=float, default=0.6, help="Ratio IS (0-1)")
    p_dates.add_argument("--num-oos", type=int, default=3, help="Períodos OOS para walk-forward")
    p_dates.add_argument("-o", "--output", help="Salida JSON")
    p_dates.set_defaults(func=cmd_date_optimizer)

    args = ap.parse_args(argv)
    if not args.command:
        ap.print_help()
        return 1
    return args.func(args)



def cmd_date_optimizer(args):
    """Optimiza rangos IS/OOS basados en datos históricos."""
    print(f"Analizando {args.symbol} ({args.timeframe}, {args.period})...")
    print(f"  Fuente: {args.source}")
    
    # Descargar datos
    try:
        if args.source == "yfinance":
            data_path = download_yfinance(symbol=args.symbol, timeframe=args.timeframe, period=args.period)
        elif args.source == "dukascopy":
            data_path = download_dukascopy(symbol=args.symbol, timeframe=args.timeframe.replace("m", "").replace("h", "H"))
    except ImportError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    
    # Cargar y analizar
    df = load_data(data_path)
    analysis = optimize_date_ranges(df, is_ratio=args.is_ratio, num_oos_periods=args.num_oos)
    
    # Guardar
    out = Path(args.output) if args.output else Path(f"date_opt_{args.symbol}_{args.timeframe}.json")
    out.write_text(json.dumps(analysis, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    
    # Mostrar resumen
    print(f"\n✓ Optimización de fechas → {out}")
    print(f"  Datos: {analysis['data_info']['total_years']} años ({analysis['data_info']['total_bars']} barras)")
    print(f"  Regímenes detectados: {len(analysis['regimes'])}")
    print(f"  Propuestas generadas: {len(analysis['proposals'])}")
    
    rec = analysis.get('recommendation', {})
    print(f"\n  Recomendación: {rec.get('strategy', 'N/A')}")
    print(f"  {rec.get('rationale', '')}")
    if rec.get('optimal_is_years'):
        print(f"  IS óptimo: {rec['optimal_is_years']} años")
        print(f"  OOS óptimo: {rec['optimal_oos_years']} años")
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
