"""Data Downloader — descarga datos históricos de Dukascopy y yfinance.

Los datos se guardan en formato Parquet (compresión columnar) para lectura rápida.
Se usa cache: si el archivo ya existe, actualiza solo los datos faltantes.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd


def _optimize_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    """Optimiza tipos de datos para Parquet."""
    for col in ["open", "high", "low", "close", "volume"]:
        if col in df.columns:
            df[col] = df[col].astype("float32")
    return df


def _merge_and_save(df_existing: pd.DataFrame, df_new: pd.DataFrame, out_path: Path) -> int:
    """Mergea datos existentes con nuevos, elimina duplicados y guarda."""
    if df_new.empty:
        return 0
    
    # Concatenar y eliminar duplicados por timestamp
    df = pd.concat([df_existing, df_new], ignore_index=True)
    df = df.drop_duplicates(subset=["timestamp"], keep="last")
    df = df.sort_values("timestamp").reset_index(drop=True)
    
    df = _optimize_dtypes(df)
    df.to_parquet(out_path, index=False, compression="snappy")
    return len(df_new)


def download_dukascopy(
    symbol: str = "EURUSD",
    timeframe: str = "H1",
    start: str = "2020-01-01",
    end: str = None,
    output_dir: str = "./data",
    force_download: bool = False,
) -> Path:
    """Descarga datos históricos de Dukascopy (gratis).
    
    Si el archivo ya existe, actualiza solo los datos faltantes desde la última fecha.
    """
    try:
        import dukascopy_python
        from dukascopy_python import instruments
    except ImportError:
        raise ImportError("dukascopy-python no instalado. Ejecuta: pip install dukascopy-python")
    
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    out_path = out_dir / f"{symbol.upper()}_{timeframe}_{start}_{end}.parquet"
    
    # Datos existentes (si hay cache)
    df_existing = pd.DataFrame()
    last_date = None
    
    if out_path.exists() and not force_download:
        df_existing = pd.read_parquet(out_path)
        if not df_existing.empty and "timestamp" in df_existing.columns:
            last_date = df_existing["timestamp"].max()
            print(f"✓ Cache encontrado: {out_path} ({len(df_existing)} barras, hasta {last_date})")
    
    # Determinar rango de descarga
    if last_date is not None:
        # Empezar desde el día siguiente a la última fecha
        fetch_start = last_date + timedelta(days=1)
        fetch_start_str = fetch_start.strftime("%Y-%m-%d")
        
        # Si ya estamos al día, no descargar
        if fetch_start.strftime("%Y-%m-%d") > end:
            print(f"✓ Datos actualizados hasta {last_date}")
            return out_path
    else:
        fetch_start_str = start
    
    # Instrumento e intervalo
    instrument_map = {
        "EURUSD": instruments.INSTRUMENT_FX_MAJORS_EUR_USD,
        "GBPUSD": instruments.INSTRUMENT_FX_MAJORS_GBP_USD,
        "USDJPY": instruments.INSTRUMENT_FX_MAJORS_USD_JPY,
        "AUDUSD": instruments.INSTRUMENT_FX_MAJORS_AUD_USD,
        "USDCAD": instruments.INSTRUMENT_FX_MAJORS_USD_CAD,
        "USDCHF": instruments.INSTRUMENT_FX_MAJORS_USD_CHF,
        "NZDUSD": instruments.INSTRUMENT_FX_MAJORS_NZD_USD,
        "EURGBP": instruments.INSTRUMENT_FX_CROSSES_EUR_GBP,
        "EURJPY": instruments.INSTRUMENT_FX_CROSSES_EUR_JPY,
        "GBPJPY": instruments.INSTRUMENT_FX_CROSSES_GBP_JPY,
        "NAS100": instruments.INSTRUMENT_IDX_AMERICA_E_NQ_100,
    }
    
    instrument = instrument_map.get(symbol.upper())
    if instrument is None:
        raise ValueError(f"Instrumento no soportado: {symbol}. Opciones: {list(instrument_map.keys())}")
    
    interval_map = {
        "M1": dukascopy_python.INTERVAL_MIN_1,
        "M5": dukascopy_python.INTERVAL_MIN_5,
        "M15": dukascopy_python.INTERVAL_MIN_15,
        "H1": dukascopy_python.INTERVAL_HOUR_1,
        "H4": dukascopy_python.INTERVAL_HOUR_4,
        "D1": dukascopy_python.INTERVAL_DAY_1,
    }
    
    interval = interval_map.get(timeframe)
    if interval is None:
        raise ValueError(f"Temporalidad no soportada: {timeframe}. Opciones: {list(interval_map.keys())}")
    
    # Descargar datos nuevos
    start_dt = datetime.strptime(fetch_start_str, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    
    print(f"  Descargando desde {fetch_start_str} hasta {end}...")
    
    df_new = dukascopy_python.fetch(
        instrument,
        interval,
        dukascopy_python.OFFER_SIDE_BID,
        start_dt,
        end_dt,
    )
    
    if df_new.empty:
        print(f"✓ No hay datos nuevos desde {fetch_start_str}")
        return out_path
    
    # Preparar datos nuevos
    df_new = df_new.reset_index()
    df_new.columns = [c.lower().replace(" ", "_") for c in df_new.columns]
    df_new = df_new.rename(columns={"datetime": "timestamp", "date": "timestamp"})
    
    # Mergear y guardar
    added = _merge_and_save(df_existing, df_new, out_path)
    total = len(df_existing) + added
    
    print(f"✓ {added} barras nuevas añadidas (total: {total}) → {out_path}")
    return out_path


def download_yfinance(
    symbol: str = "NQ=F",
    timeframe: str = "60m",
    period: str = "2y",
    output_dir: str = "./data",
    force_download: bool = False,
) -> Path:
    """Descarga datos históricos de Yahoo Finance (gratis).
    
    Si el archivo ya existe, actualiza solo los datos faltantes desde la última fecha.
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance no instalado. Ejecuta: pip install yfinance")
    
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    out_path = out_dir / f"{symbol.replace('=', '_')}_{timeframe}_{period}.parquet"
    
    # Datos existentes
    df_existing = pd.DataFrame()
    last_date = None
    
    if out_path.exists() and not force_download:
        df_existing = pd.read_parquet(out_path)
        if not df_existing.empty and "timestamp" in df_existing.columns:
            last_date = df_existing["timestamp"].max()
            print(f"✓ Cache encontrado: {out_path} ({len(df_existing)} barras, hasta {last_date})")
    
    # Descargar datos (yfinance no soporta start/end, descarga todo)
    # Si ya tenemos datos, descargar solo el período necesario
    if last_date is not None:
        # Descargar desde la última fecha hasta hoy
        fetch_start = last_date.strftime("%Y-%m-%d")
        print(f"  Descargando desde {fetch_start}...")
        
        ticker = yf.Ticker(symbol)
        df_new = ticker.history(start=fetch_start, interval=timeframe)
    else:
        ticker = yf.Ticker(symbol)
        df_new = ticker.history(period=period, interval=timeframe)
    
    if df_new.empty:
        print("✓ No hay datos nuevos")
        return out_path
    
    df_new = df_new.reset_index()
    df_new.columns = [c.lower().replace(" ", "_") for c in df_new.columns]
    df_new = df_new.rename(columns={"datetime": "timestamp", "date": "timestamp"})
    
    # Mergear y guardar
    added = _merge_and_save(df_existing, df_new, out_path)
    total = len(df_existing) + added
    
    print(f"✓ {added} barras nuevas añadidas (total: {total}) → {out_path}")
    return out_path


def load_data(path: str | Path) -> pd.DataFrame:
    """Carga datos desde Parquet (rápido)."""
    return pd.read_parquet(path)


def list_cache(output_dir: str = "./data") -> list[Path]:
    """Lista archivos en cache."""
    out_dir = Path(output_dir)
    if not out_dir.exists():
        return []
    return sorted(out_dir.glob("*.parquet"))


def clear_cache(output_dir: str = "./data") -> int:
    """Elimina archivos de cache. Retorna cantidad eliminada."""
    out_dir = Path(output_dir)
    if not out_dir.exists():
        return 0
    files = list(out_dir.glob("*.parquet"))
    for f in files:
        f.unlink()
    return len(files)
