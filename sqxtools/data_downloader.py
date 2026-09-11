"""Data Downloader — descarga datos históricos de Dukascopy y yfinance."""

import csv
import io
import os
import time
import urllib.request
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd


def download_dukascopy(
    symbol: str = "EURUSD",
    timeframe: str = "H1",  # M1, M5, M15, H1, H4, D1
    start: str = "2020-01-01",
    end: str = None,
    output_dir: str = "./data",
) -> Path:
    """Descarga datos históricos de Dukascopy (gratis).
    
    Args:
        symbol: Par de divisas (ej: EURUSD, GBPUSD, USDJPY)
        timeframe: Temporalidad (M1, M5, M15, H1, H4, D1)
        start: Fecha inicio (YYYY-MM-DD)
        end: Fecha fin (YYYY-MM-DD), por defecto hoy
        output_dir: Directorio de salida
        
    Returns:
        Path al archivo CSV descargado
    """
    if end is None:
        end = datetime.now().strftime("%Y-%m-%d")
    
    start_dt = datetime.strptime(start, "%Y-%m-%d")
    end_dt = datetime.strptime(end, "%Y-%m-%d")
    
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    all_bars = []
    current = start_dt
    
    while current <= end_dt:
        year = current.year
        month = current.month
        
        # URL de Dukascopy data feed
        if timeframe == "M1":
            url = f"https://data-feed.dukascopy.com/datafeed/{symbol.upper()}/{year}/{month:02d}/{current.day:02d}/BID_candles_M1.csv.gz"
            tf = "M1"
        elif timeframe == "M5":
            url = f"https://data-feed.dukascopy.com/datafeed/{symbol.upper()}/{year}/{month:02d}/{current.day:02d}/BID_candles_M5.csv.gz"
            tf = "M5"
        elif timeframe == "M15":
            url = f"https://data-feed.dukascopy.com/datafeed/{symbol.upper()}/{year}/{month:02d}/{current.day:02d}/BID_candles_M15.csv.gz"
            tf = "M15"
        elif timeframe == "H1":
            url = f"https://data-feed.dukascopy.com/datafeed/{symbol.upper()}/{year}/{month:02d}/{current.day:02d}/BID_candles_H1.csv.gz"
            tf = "H1"
        elif timeframe == "H4":
            url = f"https://data-feed.dukascopy.com/datafeed/{symbol.upper()}/{year}/{month:02d}/{current.day:02d}/BID_candles_H4.csv.gz"
            tf = "H4"
        elif timeframe == "D1":
            url = f"https://data-feed.dukascopy.com/datafeed/{symbol.upper()}/{year}/{month:02d}/{current.day:02d}/BID_candles_DAY.csv.gz"
            tf = "D1"
        else:
            raise ValueError(f"Temporalidad no soportada: {timeframe}")
        
        # Descargar gzip
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read()
            
            # Descomprimir
            import gzip
            with gzip.open(io.BytesIO(data), "rt") as f:
                reader = csv.reader(f)
                header = next(reader)
                
                for row in reader:
                    if len(row) >= 6:
                        timestamp = datetime.fromtimestamp(int(row[0]) / 1000)
                        if start_dt <= timestamp <= end_dt:
                            all_bars.append({
                                "timestamp": timestamp,
                                "open": float(row[1]),
                                "high": float(row[3]),
                                "low": float(row[4]),
                                "close": float(row[2]),
                                "volume": float(row[5]),
                            })
            
            time.sleep(0.2)  # Rate limit
            
        except Exception as e:
            # Si falla, continuar
            pass
        
        current += timedelta(days=1)
        
        # Limitar a no más de 31 días por llamada
        if current.day == 1:
            current = current.replace(day=28)  # Saltar al siguiente mes
    
    # Guardar CSV
    if all_bars:
        df = pd.DataFrame(all_bars)
        df = df.sort_values("timestamp").reset_index(drop=True)
        
        out_path = out_dir / f"{symbol.upper()}_{timeframe}_{start}_{end}.csv"
        df.to_csv(out_path, index=False)
        print(f"✓ {len(df)} barras descargadas → {out_path}")
        return out_path
    else:
        raise ValueError("No se pudieron descargar datos de Dukascopy")


def download_yfinance(
    symbol: str = "NQ=F",  # NAS100 futures
    timeframe: str = "60m",  # 1m, 5m, 15m, 30m, 60m, 1h
    period: str = "2y",  # 1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max
    output_dir: str = "./data",
) -> Path:
    """Descarga datos históricos de Yahoo Finance (gratis).
    
    Args:
        symbol: Ticker (NQ=F para NAS100, YM=F para Dow, ES=F para S&P)
        timeframe: Temporalidad (1m, 5m, 15m, 30m, 60m, 1h, 1d)
        period: Período de datos
        output_dir: Directorio de salida
        
    Returns:
        Path al archivo CSV descargado
    """
    try:
        import yfinance as yf
    except ImportError:
        raise ImportError("yfinance no instalado. Ejecuta: pip install yfinance")
    
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    
    ticker = yf.Ticker(symbol)
    df = ticker.history(period=period, interval=timeframe)
    
    if df.empty:
        raise ValueError(f"No se obtuvieron datos de {symbol}")
    
    df = df.reset_index()
    df.columns = [c.lower().replace(" ", "_") for c in df.columns]
    
    # Renombrar columnas para consistencia
    col_map = {
        "datetime": "timestamp",
        "date": "timestamp",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "volume": "volume",
    }
    df = df.rename(columns=col_map)
    
    out_path = out_dir / f"{symbol.replace('=', '_')}_{timeframe}_{period}.csv"
    df.to_csv(out_path, index=False)
    print(f"✓ {len(df)} barras descargadas → {out_path}")
    return out_path


def load_data(path: str | Path) -> pd.DataFrame:
    """Carga datos desde CSV."""
    df = pd.read_csv(path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df
