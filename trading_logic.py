import pandas as pd
import pandas_ta as ta
import logging

def create_dataframe(klines):
    """
    Converts k-line data from Binance into a pandas DataFrame.
    """
    if not klines:
        return pd.DataFrame()
        
    # Binance k-line format
    columns = [
        'Open_Time', 'Open', 'High', 'Low', 'Close', 'Volume', 
        'Close_Time', 'Quote_Asset_Volume', 'Number_of_Trades', 
        'Taker_Buy_Base_Asset_Volume', 'Taker_Buy_Quote_Asset_Volume', 'Ignore'
    ]
    
    df = pd.DataFrame(klines, columns=columns)
    
    # Convert necessary columns to numeric
    numeric_cols = ['Open', 'High', 'Low', 'Close', 'Volume']
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col])
        
    # Convert time to datetime (optional but good practice)
    df['Open_Time'] = pd.to_datetime(df['Open_Time'], unit='ms')
    
    return df[numeric_cols + ['Open_Time']]

def add_indicators(df):
    """
    Adds technical indicators to the DataFrame using pandas-ta.
    """
    if df.empty:
        return df

    # Bollinger Bands
    df.ta.bbands(length=20, std=2, append=True)
    
    # MACD
    df.ta.macd(fast=12, slow=26, signal=9, append=True)
    
    # Volume Moving Average
    df['Volume_MA_20'] = df['Volume'].rolling(window=20).mean()
    
    return df.dropna()

def get_signal(df):
    """
    Analyzes the latest completed candle to generate a trading signal.
    """
    if df.empty:
        return 'HOLD'

    # Get the last *completed* candle (index -2)
    # Index -1 is the current, in-progress candle
    if len(df) < 2:
        logging.warning("Not enough data to get a signal.")
        return 'HOLD'
        
    last_candle = df.iloc[-2]
    
    # --- Define Strategy ---
    
    # Bollinger Bands
    bb_lower = last_candle['BBL_20_2.0']
    bb_upper = last_candle['BBU_20_2.0']
    
    # MACD
    macd_hist = last_candle['MACDh_12_26_9']
    
    # Volume
    volume = last_candle['Volume']
    volume_ma = last_candle['Volume_MA_20']

    # --- Buy Logic ---
    # 1. Price is below lower Bollinger Band (mean reversion)
    # 2. MACD Histogram is positive (confirming bullish momentum)
    # 3. Volume is above average (confirming signal strength)
    is_buy = (
        last_candle['Close'] < bb_lower and
        macd_hist > 0 and
        volume > volume_ma
    )
    
    # --- Sell Logic ---
    # 1. Price is above upper Bollinger Band (mean reversion)
    # 2. MACD Histogram is negative (confirming bearish momentum)
    # 3. Volume is above average (confirming signal strength)
    is_sell = (
        last_candle['Close'] > bb_upper and
        macd_hist < 0 and
        volume > volume_ma
    )

    # --- Determine Signal ---
    if is_buy:
        return 'BUY'
    elif is_sell:
        return 'SELL'
    else:
        return 'HOLD'