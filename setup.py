"""Setup de SQXTools — toolkit para parsear y analizar configs de StrategyQuant."""

from setuptools import setup, find_packages

setup(
    name="sqxtools",
    version="0.4.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    install_requires=[
        "pandas>=2.0",
        "numpy>=1.24",
        "pyarrow>=14.0",
    ],
    extras_require={
        "data": [
            "yfinance>=0.2.40",
            "dukascopy-python>=0.1.5",
        ],
        "yaml": ["pyyaml>=6.0"],
        "dev": ["pytest>=7.0"],
    },
    entry_points={
        "console_scripts": [
            "sqxtools=sqxtools.cli:main",
        ],
    },
    python_requires=">=3.11",
    author="Sebastian Cardoza",
    description="Parser y analizador de .cfx/.sqb de StrategyQuant — modelos legibles por IA",
    license="MIT",
)
