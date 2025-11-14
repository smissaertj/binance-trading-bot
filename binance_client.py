import os
import logging
# Use AsyncClient for non-blocking operations
from binance.client import AsyncClient
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
        Fetches the exchange info for a specific symbol to get filters.
        """
        if not self.client:
            raise ConnectionError("Client not connected. Call connect() first.")
        
        try:
            info = await self.client.get_exchange_info()
            for s in info['symbols']:
                if s['symbol'] == symbol:
                    return s
            return None
        except BinanceAPIException as e:
            logging.error(f"Error fetching exchange info for {symbol}: {e}")
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

    async def place_order(self, symbol, side, order_type, quantity=None, quote_order_qty=None):
        """
        Places an order asynchronously. Gated by the LIVE_TRADING switch.
        Can handle orders by base asset 'quantity' (for SELLs)
        or quote asset 'quote_order_qty' (for BUYs).
        """
        if not self.client:
            raise ConnectionError("Client not connected. Call connect() first.")

        if not self.live_trading:
            logging.warning(f"PAPER MODE: Would place {side} {order_type} order for {symbol}.")
            if quote_order_qty:
                logging.warning(f"    (Quote Amount: {quote_order_qty} {symbol[-4:]})")
            if quantity:
                logging.warning(f"    (Base Quantity: {quantity} {symbol[:4]})")
            return {'paper_trade': True, 'side': side, 'symbol': symbol, 'quantity': quantity, 'quote_order_qty': quote_order_qty}

        try:
            if side.upper() == 'BUY':
                if quote_order_qty:
                    # Use quote_order_qty for fixed-USDC buys
                    logging.info(f"Placing LIVE BUY order: {quote_order_qty} {symbol[-4:]} of {symbol}")
                    return await self.client.order_market_buy(symbol=symbol, quoteOrderQty=quote_order_qty)
                elif quantity:
                    # Fallback for old method if needed
                    logging.info(f"Placing LIVE BUY order: {quantity} {symbol[:4]}")
                    return await self.client.order_market_buy(symbol=symbol, quantity=quantity)
            
            elif side.upper() == 'SELL':
                if quantity:
                     # Sells MUST use base asset quantity
                    logging.info(f"Placing LIVE SELL order: {quantity} {symbol[:4]}")
                    return await self.client.order_market_sell(symbol=symbol, quantity=quantity)
                else:
                    logging.error(f"SELL order for {symbol} must have a 'quantity'.")
                    return None
                
        except BinanceAPIException as e:
            logging.error(f"Error placing {side} order for {symbol}: {e}")
            return None