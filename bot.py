import asyncio
import logging
import math
from dotenv import load_dotenv

import trading_logic
from binance_client import BinanceClient
from binance import BinanceSocketManager

# --- Configuration ---
load_dotenv()  # Load environment variables from .env file

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("trading_bot.log"),
        logging.StreamHandler()
    ]
)

# --- Define Pairs to Trade ---
PAIRS_TO_TRADE = [
    {
        'symbol': 'ETHUSDC',
        'base_asset': 'ETH',
        'quote_asset': 'USDC',
        'interval': '1h',
        'trade_amount_usdc': 50  # Spend $50 USDC per BUY trade
    }
]

class Trader:
    """
    Encapsulates the trading logic for a single trading pair.
    This is triggered by the websocket_bot, not a loop.
    """
    def __init__(self, client, config, symbol_info):
        self.client = client # This is our async BinanceClient wrapper
        self.symbol = config['symbol']
        self.base_asset = config['base_asset']
        self.quote_asset = config['quote_asset']
        self.interval = config['interval']
        self.trade_amount_usdc = config['trade_amount_usdc']
        self.step_size = 0.0
        self.tick_size = 0.0

        self._process_symbol_info(symbol_info)
        
        logging.info(f"Trader for {self.symbol} initialized.")
        logging.info(f" -> Trade Amount (USDC): {self.trade_amount_usdc}")
        logging.info(f" -> Step Size (Quantity): {self.step_size}")

    def _process_symbol_info(self, symbol_info):
        """
        Extracts the 'stepSize' from the LOT_SIZE filter for formatting sell orders.
        """
        if not symbol_info:
            logging.warning(f"Could not get symbol info for {self.symbol}. Using default step_size.")
            self.step_size = 0.0001 # Default fallback
            return
            
        try:
            for f in symbol_info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    self.step_size = float(f['stepSize'])
                    break
        except Exception as e:
            logging.error(f"Error processing symbol info: {e}")
            self.step_size = 0.0001 # Default fallback

    def _floor_to_step(self, quantity):
        """
        Formats the sell quantity to the correct precision (step_size).
        e.g., if step_size is 0.01, quantity 1.2345 becomes 1.23
        """
        if self.step_size == 0.0:
            return quantity # Should not happen if init is correct

        # Calculate the number of decimal places from step_size
        # e.g., 0.001 -> 3 decimal places
        decimals = -int(math.log10(self.step_size))
        
        # Calculate factor, floor, and then divide
        # e.g., 0.01666 ETH, decimals = 4 -> step_size 0.0001
        # factor = 10000
        # math.floor(0.01666 * 10000) / 10000 = math.floor(166.6) / 10000 = 166 / 10000 = 0.0166
        factor = 10 ** decimals
        return math.floor(quantity * factor) / factor


    async def run_check(self):
        """
        Fetches data, analyzes it, and places an order if conditions are met.
        This is now an async function.
        """
        
        logging.info(f"--- Checking {self.symbol} ---")

        # 1. Get Data
        klines = await self.client.get_klines(self.symbol, self.interval, limit=100)
        df = trading_logic.create_dataframe(klines)
        if df.empty:
            logging.warning(f"Could not create DataFrame for {self.symbol}")
            return
            
        # 2. Get Indicators
        df_with_indicators = trading_logic.add_indicators(df)

        # 3. Get Signal (This function is synchronous, which is fine)
        signal = trading_logic.get_signal(df_with_indicators)
        logging.info(f"Signal for {self.symbol}: {signal}")

        # 4. Get Account State (Balances)
        try:
            base_balance = await self.client.get_balance(self.base_asset)
            quote_balance = await self.client.get_balance(self.quote_asset)
            logging.info(f"Balances: {base_balance} {self.base_asset}, {quote_balance} {self.quote_asset}")
        except Exception as e:
            logging.error(f"Could not get balances for {self.symbol}: {e}")
            return

        # 5. Execute Logic (New logic based on USDC amount)
        
        if signal == 'BUY':
            if base_balance > (self.step_size * 5): 
                # Check if we already hold a position (more than 5x the min step size)
                logging.info(f"BUY signal, but already hold {self.base_asset}. Holding.")
            elif quote_balance < self.trade_amount_usdc:
                # Check if we have enough USDC to make the trade
                logging.info(f"BUY signal, but not enough {self.quote_asset}. Need {self.trade_amount_usdc}.")
            else:
                logging.info(f"BUY signal detected. Placing order for {self.trade_amount_usdc} {self.quote_asset}.")
                await self.client.place_order(
                    self.symbol, 'BUY', 'MARKET', quote_order_qty=self.trade_amount_usdc
                )

        elif signal == 'SELL':
            if base_balance > (self.step_size * 5): # Check if we have a position to sell
                
                # Format the quantity to the correct step size
                sell_quantity = self._floor_to_step(base_balance)
                logging.info(f"SELL signal detected. Selling {sell_quantity} {self.base_asset}.")
                
                await self.client.place_order(
                    self.symbol, 'SELL', 'MARKET', quantity=sell_quantity
                )
            else:
                logging.info(f"SELL signal, but no {self.base_asset} to sell. Holding.")

        elif signal == 'HOLD':
            logging.info(f"HOLD signal. No action taken for {self.symbol}.")


async def main():
    """
    Main bot entry point.
    Initializes the client, creates Trader instances, and starts the websocket.
    """
    logging.info("Starting websocket trading bot...")
    
    client = None
    socket_manager = None
    try:
        # Initialize our async client wrapper
        client = BinanceClient()
        await client.connect() # This creates the AsyncClient

        # --- Fetch symbol info BEFORE creating traders ---
        traders = {}
        for config in PAIRS_TO_TRADE:
            symbol = config['symbol'].upper()
            symbol_info = await client.get_symbol_info(symbol)
            if not symbol_info:
                logging.error(f"Could not get symbol info for {symbol}. Skipping this pair.")
                continue
            
            traders[symbol] = Trader(client, config, symbol_info)

        # Create a dictionary of Trader instances, keyed by symbol
        # traders = {
        #     config['symbol'].upper(): Trader(client, config) 
        #     for config in PAIRS_TO_TRADE
        # }
        
        # Get the underlying AsyncClient to pass to the socket manager
        # This is a bit of a pattern: our wrapper manages the client,
        # but the socket manager needs the raw client object.
        raw_async_client = client.client
        socket_manager = BinanceSocketManager(raw_async_client)

        async def handle_socket_message(msg):
            """
            This is the callback function that the websocket will call.
            """
            # Uncomment to see all messages (can be noisy)
            # logging.debug(f"Socket message: {msg}")
            
            # Check for errors
            if msg.get('e') == 'error':
                logging.error(f"Socket Error: {msg.get('m')}")
                return

            # Check if it's a kline message
            if msg.get('e') == 'kline':
                symbol = msg['s'].upper()
                kline = msg['k']
                is_closed = kline['x']
                interval = kline['i']

                # Find the trader for this symbol
                trader = traders.get(symbol)
                if not trader:
                    return # Not a symbol we are trading

                # Check if it's the correct interval and if the candle is closed
                if interval == trader.interval and is_closed:
                    logging.info(f"--- New candle closed for {symbol} ---")
                    # Run the trading logic check
                    try:
                        await trader.run_check()
                    except Exception as e:
                        logging.error(f"Error in trader.run_check() for {symbol}: {e}")

        # --- Setup the websocket streams ---
        
        # We need to create a list of socket connection "keys"
        # e.g., ['ethusdc@kline_1h', 'btcusdc@kline_1h']
        socket_streams = [
            f"{config['symbol'].lower()}@kline_{config['interval']}"
            for config in PAIRS_TO_TRADE
        ]
        
        if not socket_streams:
            logging.error("No pairs to trade. Exiting.")
            return

        logging.info(f"Subscribing to streams: {socket_streams}")
        
        # Start the multiplex socket
        # The 'handle_socket_message' function will be called for every message
        async with socket_manager.multiplex_socket(socket_streams) as ms:
            while True:
                try:
                    msg = await ms.recv()
                    await handle_socket_message(msg)
                except Exception as e:
                    logging.error(f"Error processing websocket message: {e}")
                    # Brief sleep to prevent rapid-fire error loops
                    await asyncio.sleep(5)

    except Exception as e:
        logging.error(f"An unexpected error occurred in main: {e}")
    finally:
        if client:
            await client.close()
        logging.info("Bot shutting down.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Shutdown initiated by user.")