"""Configuración compartida para tests."""

from pathlib import Path

# Ruta a fixtures (.cfx reales y sintéticos)
FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Tamaño máximo de fixtures a cargar en tests (para no llenar la memoria)
MAX_FIXTURE_SIZE = 5 * 1024 * 1024  # 5 MB
