# SQXTools

Parser de StrategyQuant .cfx — convierte building config / build / retester / optimizer config en JSON legible para IA.

## Estructura

```
sqxtools/
├── __init__.py
├── parser.py        # Parsea .cfx → modelo Python
├── serializer.py    # Modelo Python → JSON/Markdown
├── cli.py           # Interfaz de línea de comandos
├── models.py        # Definición del modelo (dataclasses)
├── patterns.py      # Patrones/indicadores reconocidos
└── tests/
    ├── __init__.py
    ├── test_parser.py
    └── fixtures/
        └── .cfx de ejemplo
```

## Uso

```bash
python -m sqxtools.cli path/al/archivo.cfx -o output.json
```

## Roadmap

- [x] Crear esqueleto
- [ ] Parser de .cfx real
- [ ] Modelo canónico
- [ ] Serializer JSON
- [ ] Tests con fixtures reales
