import asyncio
import logging
import math
import os
from dotenv import load_dotenv

import trading_logic
from binance_client import BinanceClient
from binance import BinanceSocketManager

# --- Configuration ---
load_dotenv()
TRADE_MOUNT_USDC = os.getenv('TRADE_MOUNT_USDC', '50')


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
logging.info(f"Using trade amount: ${TRADE_MOUNT_USDC} USDC")
PAIRS_TO_TRADE = [
    {
        'symbol': 'ETHUSDC',
        'base_asset': 'ETH',
        'quote_asset': 'USDC',
        'interval': '1h',                # The interval for our main BUY/SELL signals
        'trade_amount_usdc': 50,     # Spend $50 USDC per BUY trade
        
        # --- Risk Management ---
        'stop_loss_pct': 0.05,           # 5% stop-loss (e.g., sell if price drops 5% below entry)
        'trailing_stop_pct': 0.02,       # 2% trailing stop (e.g., keep stop 2% below the highest price)
        'take_profit_pct': 0.10,         # 10% take profit (e.g., sell if price rises 10% above entry)
    },
]

class Trader:
    """
    Encapsulates the trading logic and state for a single trading pair.
    """
    def __init__(self, client, config, symbol_info):
        self.client = client
        self.symbol = config['symbol']
        self.base_asset = config['base_asset']
        self.quote_asset = config['quote_asset']
        self.signal_interval = config['interval'] # e.g., '1h'
        self.trade_amount_usdc = config['trade_amount_usdc']

        # Risk parameters
        self.stop_loss_pct = config['stop_loss_pct']
        self.trailing_stop_pct = config['trailing_stop_pct']
        self.take_profit_pct = config['take_profit_pct']

        # Symbol filters
        self.step_size = 0.0
        self._process_symbol_info(symbol_info)

        # --- State ---
        self.in_position = False
        self.entry_price = 0.0
        self.stop_loss_price = 0.0
        self.take_profit_price = 0.0
        
        logging.info(f"Trader for {self.symbol} initialized.")
        logging.info(f" -> Trade Amount (USDC): {self.trade_amount_usdc}")
        logging.info(f" -> Stop-Loss: {self.stop_loss_pct*100}%")
        logging.info(f" -> Trailing Stop: {self.trailing_stop_pct*100}%")

    async def initialize_state(self):
        """
        Checks current balance on startup to see if we are already in a position.
        This is crucial for bot restarts.
        """
        try:
            base_balance = await self.client.get_balance(self.base_asset)
            # Check if we hold a significant amount (more than 5x the min step size)
            if base_balance > (self.step_size * 5):
                logging.warning(f"Bot restart: Already in position with {base_balance} {self.base_asset}.")
                logging.warning("Please set state manually or sell asset to start fresh.")
                # In a real system, you would load self.entry_price from a database here.
                # For this MVP, we assume a clean start or manual intervention.
                # self.in_position = True
                # self.entry_price = ... (load from db)
                # self.stop_loss_price = ... (load from db)
            else:
                self.in_position = False
                logging.info(f"Bot starting with no {self.base_asset} position. Ready to buy.")
        except Exception as e:
            logging.error(f"Error initializing state: {e}")

    def _process_symbol_info(self, symbol_info):
        if not symbol_info:
            logging.warning(f"Could not get symbol info for {self.symbol}. Using default step_size.")
            self.step_size = 0.0001
            return
        try:
            for f in symbol_info['filters']:
                if f['filterType'] == 'LOT_SIZE':
                    self.step_size = float(f['stepSize'])
                    break
        except Exception as e:
            logging.error(f"Error processing symbol info: {e}")
            self.step_size = 0.0001

    def _floor_to_step(self, quantity):
        if self.step_size == 0.0:
            return quantity
        decimals = -int(math.log10(self.step_size))
        factor = 10 ** decimals
        return math.floor(quantity * factor) / factor

    def _calculate_avg_fill_price(self, order):
        """Calculates the average fill price from a Binance order object."""
        try:
            cummulative_quote_qty = float(order['cummulativeQuoteQty'])
            executed_qty = float(order['executedQty'])
            if executed_qty > 0:
                return cummulative_quote_qty / executed_qty
        except (KeyError, ValueError, ZeroDivisionError) as e:
            logging.error(f"Could not calculate average price from order: {order}. Error: {e}")
        return None

    async def _enter_position(self, current_price):
        """
        Handles the logic for entering a BUY position.
        """
        logging.info(f"BUY signal. Placing order for {self.trade_amount_usdc} {self.quote_asset}.")
        order = await self.client.place_order(
            self.symbol, 'BUY', 'MARKET', quote_order_qty=self.trade_amount_usdc
        )
        
        if not order:
            logging.error(f"Failed to enter position for {self.symbol}. Order was None.")
            return

        # Determine the entry price based on trade type
        if order.get('paper_trade'):
            entry_price = current_price # Approximation for paper trading
            logging.info("Paper trade: using current kline price as approximate entry.")
        
        elif order.get('status') == 'FILLED':
            entry_price = self._calculate_avg_fill_price(order)
            if not entry_price:
                logging.error("Could not determine entry price from FILLED order. Aborting.")
                return
            logging.info(f"Real trade: calculated average entry price: {entry_price}")

        else:
            logging.error(f"Order was not filled or a paper trade. Status: {order.get('status')}")
            return

        # Set state based on successful order
        self.in_position = True
        self.entry_price = entry_price
        self.stop_loss_price = self.entry_price * (1 - self.stop_loss_pct)
        self.take_profit_price = self.entry_price * (1 + self.take_profit_pct)
        
        logging.info(f"--- ENTERED POSITION {self.symbol} ---")
        logging.info(f"  Entry Price: {self.entry_price}")
        logging.info(f"  Stop-Loss:   {self.stop_loss_price}")
        logging.info(f"  Take-Profit: {self.take_profit_price}")

    async def _exit_position(self, reason):
        """
        Handles the logic for exiting a SELL position.
        """
        try:
            base_balance = await self.client.get_balance(self.base_asset)
            if base_balance < (self.step_size * 5):
                logging.warning(f"Tried to sell, but no position found for {self.base_asset}.")
                self.in_position = False # Reset state
                return

            sell_quantity = self._floor_to_step(base_balance)
            logging.info(f"--- EXITING POSITION {self.symbol} ({reason}) ---")
            logging.info(f"  Selling {sell_quantity} {self.base_asset}")
            
            order = await self.client.place_order(
                self.symbol, 'SELL', 'MARKET', quantity=sell_quantity
            )
            
            if order and (order.get('paper_trade') or order.get('status') == 'FILLED'):
                # Reset state
                self.in_position = False
                self.entry_price = 0.0
                self.stop_loss_price = 0.0
                self.take_profit_price = 0.0
                logging.info(f"Position for {self.symbol} closed.")
            else:
                logging.error(f"Failed to exit position: {order}")
        except Exception as e:
            logging.error(f"Error during exit_position: {e}")

    # --- Handlers for Websocket Streams ---

    async def handle_signal_candle(self, kline):
        """
        Runs on the main strategy interval (e.g., 1h).
        Responsible for finding BUY signals and main SELL (take-profit) signals.
        """
        # 1. If we are NOT in a position, look for a BUY signal
        if not self.in_position:
            klines = await self.client.get_klines(self.symbol, self.signal_interval, limit=100)
            df = trading_logic.create_dataframe(klines)
            df_with_indicators = trading_logic.add_indicators(df)
            signal = trading_logic.get_signal(df_with_indicators)
            
            if signal == 'BUY':
                logging.info(f"SIGNAL ({self.signal_interval}): BUY signal found for {self.symbol}")
                current_price = float(kline['c']) # Get price from the candle
                await self._enter_position(current_price)
            else:
                logging.info(f"SIGNAL ({self.signal_interval}): {signal} signal. No action.")

        # 2. If we ARE in a position, check for our mean-reversion SELL signal
        #    (This acts as an *additional* take-profit, separate from the stop-loss)
        else:
            klines = await self.client.get_klines(self.symbol, self.signal_interval, limit=100)
            df = trading_logic.create_dataframe(klines)
            df_with_indicators = trading_logic.add_indicators(df)
            signal = trading_logic.get_signal(df_with_indicators)
            
            if signal == 'SELL':
                logging.info(f"SIGNAL ({self.signal_interval}): Mean-reversion SELL signal found.")
                await self._exit_position(reason="TAKE-PROFIT (Signal)")
            else:
                logging.info(f"SIGNAL ({self.signal_interval}): In position, {signal} signal. Holding.")

    async def handle_price_update(self, kline):
        """
        Runs on a fast interval (e.g., 1m).
        Responsible *only* for risk management (stop-loss, trailing stop, take-profit).
        """
        if not self.in_position:
            return # Not in a position, nothing to risk-manage

        current_price = float(kline['c']) # Close price of the 1m candle

        # 1. Check Stop-Loss
        if current_price <= self.stop_loss_price:
            logging.warning(f"RISK MGMT (1m): Price {current_price} hit STOP-LOSS {self.stop_loss_price}.")
            await self._exit_position(reason="STOP-LOSS")
            return # Exit, as we are no longer in a position

        # 2. Check Take-Profit (Fixed Percentage)
        if current_price >= self.take_profit_price:
            logging.info(f"RISK MGMT (1m): Price {current_price} hit TAKE-PROFIT {self.take_profit_price}.")
            await self._exit_position(reason="TAKE-PROFIT (Fixed)")
            return

        # 3. Check Trailing Stop-Loss
        # Calculate a new potential stop-loss based on the trailing percentage
        new_trailing_stop = current_price * (1 - self.trailing_stop_pct)
        
        # If the new trailing stop is *higher* than our current stop-loss, "trail" it up
        if new_trailing_stop > self.stop_loss_price:
            self.stop_loss_price = new_trailing_stop
            logging.debug(f"RISK MGMT (1m): Trailing stop-loss up to {self.stop_loss_price}")


async def main():
    logging.info("Starting stateful websocket trading bot...")
    
    client = None
    try:
        client = BinanceClient()
        await client.connect()
        
        traders = {}
        all_socket_streams = set()

        # Initialize all traders and get their symbol info
        for config in PAIRS_TO_TRADE:
            symbol = config['symbol'].upper()
            symbol_info = await client.get_symbol_info(symbol)
            if not symbol_info:
                logging.error(f"Could not get symbol info for {symbol}. Skipping this pair.")
                continue
            
            trader = Trader(client, config, symbol_info)
            await trader.initialize_state() # Check if we're in a position
            traders[symbol] = trader
            
            # Add this trader's streams to the global set
            # 1. The main signal stream (e.g., 1h)
            all_socket_streams.add(f"{symbol.lower()}@kline_{config['interval']}")
            # 2. The risk-management stream (1m)
            all_socket_streams.add(f"{symbol.lower()}@kline_1m")

        if not traders:
            logging.error("No traders initialized. Exiting.")
            return

        raw_async_client = client.client
        socket_manager = BinanceSocketManager(raw_async_client)
        
        logging.info(f"Subscribing to {len(all_socket_streams)} streams: {all_socket_streams}")

        async with socket_manager.multiplex_socket(list(all_socket_streams)) as ms:
            while True:
                try:
                    msg = await ms.recv()
                    
                    if msg.get('e') == 'error':
                        logging.error(f"Socket Error: {msg.get('m')}")
                        continue
                    
                    if msg.get('e') == 'kline':
                        symbol = msg['s'].upper()
                        kline = msg['k']
                        is_closed = kline['x']
                        interval = kline['i']
                        
                        trader = traders.get(symbol)
                        if not trader:
                            continue # Not a symbol we are trading
                        
                        # Is this a closed candle?
                        if is_closed:
                            # 1. Is it a SIGNAL interval candle?
                            if interval == trader.signal_interval:
                                await trader.handle_signal_candle(kline)
                            
                            # 2. Is it a RISK MGMT interval candle?
                            if interval == '1m':
                                await trader.handle_price_update(kline)

                except Exception as e:
                    logging.error(f"Error processing websocket message: {e}")
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