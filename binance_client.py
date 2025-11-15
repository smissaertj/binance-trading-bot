import os
import logging
# Use AsyncClient for non-blocking operations
from binance import AsyncClient
from binance.exceptions import BinanceAPIException

class BinanceClient:
    """
    A wrapper for the Binance API client.
    Handles testnet/live configuration and safety switches.
    Upgraded to use AsyncClient for asynchronous operations.
    """
    def __init__(self):
        self.api_key = os.getenv('BINANCE_API_KEY')
        self.api_secret = os.getenv('BINANCE_API_SECRET')

        if not self.api_key or not self.api_secret:
            logging.error("API key and secret not found. Set BINANCE_API_KEY and BINANCE_API_SECRET in .env")
            raise ValueError("Missing API Key/Secret")

        self.use_testnet = os.getenv('USE_TESTNET', 'True').lower() == 'true'
        self.live_trading = os.getenv('LIVE_TRADING', 'False').lower() == 'true'
        
        # Client will be created in the async connect method
        self.client = None

    async def connect(self):
        """
        Creates and connects the AsyncClient. Must be called after init.
        """
        try:
            self.client = await AsyncClient.create(self.api_key, self.api_secret, testnet=self.use_testnet)
            await self.client.ping()
            logging.info(f"Binance AsyncClient initialized. Testnet: {self.use_testnet}, Live Trading: {self.live_trading}")
        except Exception as e:
            logging.error(f"Failed to connect to Binance: {e}")
            raise

    async def close(self):
        """
        Closes the async client connection.
        """
        if self.client:
            await self.client.close_connection()
            logging.info("Binance client connection closed.")

    async def get_symbol_info(self, symbol):
        """
        Fetches the exchange information for a specific symbol.
        """
        if not self.client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        try:
            return await self.client.get_symbol_info(symbol)
        except BinanceAPIException as e:
            logging.error(f"Error fetching symbol info for {symbol}: {e}")
            return None

    async def get_klines(self, symbol, interval, limit=100):
        """
        Fetches historical k-line (candle) data asynchronously.
        """
        if not self.client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        try:
            return await self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        except BinanceAPIException as e:
            logging.error(f"Error fetching klines for {symbol}: {e}")
            return []

    async def get_balance(self, asset):
        """
        Fetches the free balance for a specific asset asynchronously.
        """
        if not self.client:
            raise ConnectionError("Client not connected. Call connect() first.")
            
        try:
            balance = await self.client.get_asset_balance(asset=asset)
            if balance:
                return float(balance['free'])
            return 0.0
        except BinanceAPIException as e:
            logging.error(f"Error fetching balance for {asset}: {e}")
            return 0.0

    async def place_order(self, symbol, side, order_type, **kwargs):
        """
        Places an order asynchronously. Gated by the LIVE_TRADING switch.
        Accepts kwargs to pass to the underlying client order methods.
        e.g., quantity=, quote_order_qty=
        """
        if not self.client:
            raise ConnectionError("Client not connected. Call connect() first.")

        # In paper mode, we just log the intended action and return a mock object
        if not self.live_trading:
            logging.warning(f"PAPER MODE: Would place {side} {order_type} order for {symbol} with params: {kwargs}")
            return {'paper_trade': True, 'side': side, 'symbol': symbol, **kwargs}

        try:
            if side.upper() == 'BUY':
                logging.info(f"Placing LIVE BUY order: {symbol}, params: {kwargs}")
                return await self.client.order_market_buy(symbol=symbol, **kwargs)
            
            elif side.upper() == 'SELL':
                logging.info(f"Placing LIVE SELL order: {symbol}, params: {kwargs}")
                return await self.client.order_market_sell(symbol=symbol, **kwargs)
                
        except BinanceAPIException as e:
            logging.error(f"Error placing {side} order for {symbol}: {e}")
            return None