import ccxt
import os
import threading
import time


class TradingBot:
    def __init__(self, trading_pair):
        # Load parameters from environment variables or use defaults
        self.api_key = os.getenv("API_KEY")
        self.api_secret = os.getenv("API_SECRET")
        self.trading_fee = float(os.getenv("TRADING_FEE", 0.001))  # Default Binance 0.1% Spot Trading fee
        self.spread_percentage = float(os.getenv("SPREAD_PERCENTAGE", 0.025))  # Market Making, Default 2.5% # TODO - Dynamically adjust based on market conditions.
        self.percentage_of_balance = float(os.getenv("PERCENTAGE_OF_BALANCE", 0.05))
        self.trade_interval = float(os.getenv("TRADE_INTERVAL", 30))
        self.stop_flag = threading.Event()  # Create a stop flag
        sandbox_mode = os.getenv("SANDBOX_MODE", "True").lower() in ["true", "1"]

        if not self.api_key or not self.api_secret:
            raise ValueError("API_KEY and API_SECRET environment variables must be set.")

        self.exchange = ccxt.binance({
            'apiKey': self.api_key,
            'secret': self.api_secret,
            'enableRateLimit': True,
            'options': {
                'defaultType': 'spot',
            },
        })

        self.exchange.verbose = False
        self.exchange.set_sandbox_mode(sandbox_mode)
        self.trading_pair = trading_pair
        self.position_size = 0  # To store position size for buy/sell consistency
        self.available_balance = 0  # Keep track of remaining base currency amount

        # Load markets to fetch trading pair metadata
        print("Loading Binance markets...", flush=True)
        self.exchange.load_markets()
        print("Markets loaded successfully.", flush=True)


    def fetch_market_data(self):
        try:
            ticker = self.exchange.fetch_ticker(self.trading_pair)
            return ticker
        except Exception as e:
            print(f"Error fetching market data for {self.trading_pair}: {e}", flush=True)
            return None


    def refresh_balance(self):
        try:
            balance = self.exchange.fetch_balance()
            print(f"Available USDT: {balance['USDT']['free']}", flush=True)
            print(f"Locked USDT: {balance['USDT']['used']}", flush=True)
            self.available_balance = balance['USDT']['free']
        except Exception as e:
            print(f"Error refreshing balance for {self.trading_pair}: {e}", flush=True)


    def get_minimum_notional(self):
        try:
            market = self.exchange.market(self.trading_pair)
            min_notional = market['limits']['cost']['min']  # Minimum notional value
            print(f"Market making - {self.trading_pair} - Minimum notional: {min_notional}", flush=True)
            return min_notional
        except Exception as e:
            print(f"Error fetching minimum notional for {self.trading_pair}: {e}", flush=True)
            return 0


    def get_minimum_order_size(self):
        try:
            market = self.exchange.market(self.trading_pair)
            min_order_size = market['limits']['amount']['min']  # Minimum order size
            print(f"Market making - {self.trading_pair} - Minimum order size: {min_order_size}", flush=True)
            return min_order_size
        except Exception as e:
            print(f"Error fetching minimum order size for {self.trading_pair}: {e}", flush=True)
            return 0


    def calculate_position_size(self):
        try:
            quote_currency = self.trading_pair.split('/')[1]  # Extract quote currency, e.g., 'USDT'

            # Fetch the current price of the trading pair
            ticker = self.fetch_market_data()
            if not ticker:
                raise ValueError(f"Could not fetch {self.trading_pair} market data for position size calculation.")
            current_price = ticker['last']

            # Calculate position size for buy orders
            position_size = (self.available_balance * self.percentage_of_balance) / current_price
            position_size = float(self.exchange.amount_to_precision(self.trading_pair, position_size))
            print(f"[{self.trading_pair}] Available Balance: {self.available_balance:.2f} {quote_currency}, Position Size: {position_size:.6f}", flush=True)
            return position_size
        except Exception as e:
            print(f"Error calculating position size for {self.trading_pair}: {e}", flush=True)
            return 0


    def is_downward_trend(self, period=5):
        try:
            # Fetch historical data for the trading pair
            ohlcv = self.exchange.fetch_ohlcv(self.trading_pair, timeframe='15m', limit=period)
            close_prices = [x[4] for x in ohlcv]  # Extract closing prices

            # Calculate a simple moving average
            avg_price = sum(close_prices) / len(close_prices)

            # Compare the latest price to the average
            current_price = close_prices[-1]
            print(f"Current price: {current_price}, Moving average: {avg_price}", flush=True)
            return current_price < avg_price  # Downward trend if current price < average
        except Exception as e:
            print(f"Error detecting trend for {self.trading_pair}: {e}")
            return False


    def calculate_order_prices(self, current_price):
        """Calculate buy and sell prices based on current price and spread."""
        buy_price = current_price * (1 - self.spread_percentage - self.trading_fee)
        sell_price = current_price * (1 + self.spread_percentage + self.trading_fee)
        buy_price = float(self.exchange.price_to_precision(self.trading_pair, buy_price))
        sell_price = float(self.exchange.price_to_precision(self.trading_pair, sell_price))
        return buy_price, sell_price


    def place_buy_order(self, order_size, buy_price):
        """Place a buy order."""
        try:
            buy_order = self.exchange.create_limit_buy_order(self.trading_pair, order_size, buy_price)
            print(f"Buy order placed - Price: {buy_price:.6f} - Amount: {order_size:.6f}", flush=True)
            return buy_order
        except Exception as e:
            print(f"Error placing buy order: {e}", flush=True)
            return None


    def place_sell_order(self, order_size, sell_price):
        """Place a sell order."""
        try:
            sell_order = self.exchange.create_limit_sell_order(self.trading_pair, order_size, sell_price)
            print(f"Sell order placed - Price: {sell_price:.6f} - Amount: {order_size:.6f}", flush=True)
            return sell_order
        except Exception as e:
            print(f"Error placing sell order: {e}", flush=True)
            return None


    def cancel_all_open_orders(self):
        try:
            # Fetch open orders for the current trading pair
            open_orders = self.exchange.fetch_open_orders(self.trading_pair)
            for order in open_orders:
                # Ensure the order belongs to the current trading pair
                if order['symbol'] != self.trading_pair:
                    continue

                # Fetch the latest order status
                order_status = self.exchange.fetch_order(order['id'], self.trading_pair)
                if order_status['status'] in ['closed', 'filled']:
                    print(f"Order {order['id']} already filled. Skipping adjustment.", flush=True)
                    continue

                # Cancel the order
                self.exchange.cancel_order(order['id'], self.trading_pair)
                print(f"Canceled order {order['id']} for {self.trading_pair}.", flush=True)
        except Exception as e:
            print(f"Error canceling open orders for {self.trading_pair}: {e}", flush=True)


    def adjust_orders(self):
        """Adjust existing buy and sell orders or place new ones if none exist."""
        try:
            # Fetch open orders for the current trading pair
            open_orders = self.exchange.fetch_open_orders(self.trading_pair)

            if not open_orders:
                print(f"No open orders found for {self.trading_pair}. Placing new orders.", flush=True)

                # Fetch the current market price
                ticker = self.fetch_market_data()
                if not ticker:
                    print(f"Failed to fetch market data for {self.trading_pair}.", flush=True)
                    return

                current_price = ticker['last']
                buy_price, sell_price = self.calculate_order_prices(current_price)
                order_size = self.calculate_position_size()

                # Ensure order size meets minimum requirements
                min_order_size = self.get_minimum_order_size()
                min_notional = self.get_minimum_notional()
                if order_size < min_order_size:
                    order_size = min_order_size
                notional_value = order_size * current_price
                if notional_value < min_notional:
                    buffer = 10 ** -self.exchange.markets[self.trading_pair]['precision']['amount']
                    order_size = (min_notional / current_price) + buffer
                    order_size = float(self.exchange.amount_to_precision(self.trading_pair, order_size))

                # Place new orders
                self.place_buy_order(order_size, buy_price)
                self.place_sell_order(order_size, sell_price)
                return

            # If there are open orders, adjust them
            order_book = self.exchange.fetch_order_book(self.trading_pair)
            best_bid = order_book['bids'][0][0]
            best_ask = order_book['asks'][0][0]

            # Calculate new prices
            new_buy_price = best_bid * (1 - self.trading_fee)
            new_sell_price = best_ask * (1 + self.trading_fee)

            # Ensure precision
            new_buy_price = float(self.exchange.price_to_precision(self.trading_pair, new_buy_price))
            new_sell_price = float(self.exchange.price_to_precision(self.trading_pair, new_sell_price))

            for order in open_orders:
                if order['side'] == 'buy' and abs(order['price'] - new_buy_price) > (best_bid * 0.001):
                    self.exchange.cancel_order(order['id'], self.trading_pair)
                    print(f"Adjusted buy order. New price: {new_buy_price:.6f}", flush=True)
                    self.place_buy_order(order['amount'], new_buy_price)
                elif order['side'] == 'sell' and abs(order['price'] - new_sell_price) > (best_ask * 0.001):
                    self.exchange.cancel_order(order['id'], self.trading_pair)
                    print(f"Adjusted sell order. New price: {new_sell_price:.6f}", flush=True)
                    self.place_sell_order(order['amount'], new_sell_price)

        except Exception as e:
            print(f"Error adjusting orders for {self.trading_pair}: {e}", flush=True)


    def market_making_strategy(self):
        if self.spread_percentage < 2 * self.trading_fee:
            raise ValueError(f"Spread percentage ({self.spread_percentage}) is too low to cover trading fees ({2 * self.trading_fee}%). Increase the spread.")

        while not self.stop_flag.is_set():
            try:
                while self.is_downward_trend():
                    print(f"Downward trend detected. Canceling open orders and pausing...", flush=True)
                    self.cancel_all_open_orders()
                    time.sleep(self.trade_interval)

                print(f"Market making - {self.trading_pair} - Fetching market data...", flush=True)
                ticker = self.fetch_market_data()
                if not ticker:
                    print(f"Market making - {self.trading_pair} - Failed to fetch market data.", flush=True)
                    time.sleep(5)
                    continue

                current_price = ticker['last']
                print(f"Market making - {self.trading_pair} - Current price: {current_price:.6f}", flush=True)
                self.refresh_balance()

                # Fetch market limits and calculate order size
                min_notional = self.get_minimum_notional()
                min_order_size = self.get_minimum_order_size()
                order_size = self.calculate_position_size()

                # Adjust order size for limits
                if order_size < min_order_size:
                    order_size = min_order_size
                notional_value = order_size * current_price
                if notional_value < min_notional:
                    buffer = 10 ** -self.exchange.markets[self.trading_pair]['precision']['amount']
                    order_size = (min_notional / current_price) + buffer
                    order_size = float(self.exchange.amount_to_precision(self.trading_pair, order_size))
                if self.available_balance < order_size * current_price:
                    print(f"Insufficient balance. Free USDT: {self.available_balance:.6f}, Required: {order_size * current_price:.6f}", flush=True)
                    time.sleep(30)
                    continue

                # Calculate order prices and place initial orders
                buy_price, sell_price = self.calculate_order_prices(current_price)
                buy_order = self.place_buy_order(order_size, buy_price)
                sell_order = self.place_sell_order(order_size, sell_price)

                if not buy_order or not sell_order:
                    time.sleep(5)
                    continue

                # Monitor and adjust orders dynamically
                while not self.stop_flag.is_set():
                    time.sleep(self.trade_interval)
                    self.adjust_orders()
            except Exception as e:
                print(f"Error executing market making strategy for {self.trading_pair}: {e}", flush=True)
                time.sleep(5)


    def run(self):
        self.market_making_strategy()


    def stop(self):
        self.stop_flag.set()  # Signal the bot to stop


if __name__ == "__main__":
    trading_pairs = os.getenv("TRADING_PAIRS", "ADA/USDT,CKB/USDT").split(",")
    bots = []

    # Start bots
    for i, pair in enumerate(trading_pairs):
        bot = TradingBot(trading_pair=pair)
        thread = threading.Thread(target=bot.run)
        bots.append((bot, thread))
        thread.start()
        time.sleep(5)  # Stagger starts to avoid API rate limits

    try:
        # Ensures the main program stays active and does not exit immediately after starting the threads.
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        for bot, thread in bots:
            bot.stop() # Signal each bot to stop
        for bot, thread in bots:
            thread.join() # Wait for all threads to finish

    print("All trading bots have completed execution.")