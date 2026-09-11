from setuptools import setup, find_packages

setup(
    name="sqxtools",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
    entry_points={
        "console_scripts": [
            "sqxtools=sqxtools.cli:main",
        ],
    },
    python_requires=">=3.11",
    author="Sebastian Cardoza",
    description="Parser de StrategyQuant .cfx — convierte configs en JSON legible para IA",
)
