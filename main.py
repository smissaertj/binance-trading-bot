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
        self.fixed_trade_value = float(os.getenv("FIXED_TRADE_VALUE", 6.0))  # Default to $6 per trade, Binance minimum is $5..
        self.trade_interval = float(os.getenv("TRADE_INTERVAL", 30))
        self.moving_average_timeframe = os.getenv("MOVING_EMA_TIMEFRAME", "5m")
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
        print(f"{self.trading_pair} - Loading Binance markets...", flush=True)
        self.exchange.load_markets()
        print(f"{self.trading_pair} - Markets loaded successfully.", flush=True)

        if self.fixed_trade_value < 5.0:  # Binance minimum
            raise ValueError(f"{self.trading_pair} - Fixed trade value ({self.fixed_trade_value}) must be at least $5 to meet Binance's minimum notional requirements.")


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


    def get_minimum_order_size(self):
        try:
            market = self.exchange.market(self.trading_pair)
            min_order_size = market['limits']['amount']['min']  # Minimum order size
            print(f"{self.trading_pair} - Minimum order size: {min_order_size}", flush=True)
            return min_order_size
        except Exception as e:
            print(f"Error fetching minimum order size for {self.trading_pair}: {e}", flush=True)
            return 0


    def calculate_position_size(self):
        """
        Calculate the position size based on the fixed trade value and current price.
        Ensure the size meets the minimum order size requirements.
        """
        try:
            # Fetch the current price of the trading pair
            ticker = self.fetch_market_data()
            if not ticker:
                raise ValueError(f"Could not fetch {self.trading_pair} market data for position size calculation.")
            current_price = ticker['last']

            # Calculate position size using the fixed trade value
            position_size = self.fixed_trade_value / current_price

            # Apply exchange precision
            position_size = float(self.exchange.amount_to_precision(self.trading_pair, position_size))

            # Validate against minimum order size
            min_order_size = self.get_minimum_order_size()
            if position_size < min_order_size:
                raise ValueError(
                    f"{self.trading_pair} - Calculated position size {position_size} is below the minimum order size {min_order_size}. "
                    "Consider increasing FIXED_TRADE_VALUE."
                )

            print(f"[{self.trading_pair}] - Fixed Trade Value: {self.fixed_trade_value:.2f}, Position Size: {position_size:.6f}, Current Price: {current_price:.6f}", flush=True)
            return position_size

        except Exception as e:
            print(f"Error calculating position size for {self.trading_pair}: {e}", flush=True)
            return 0


    def is_downward_trend(self, period=5):
        try:
            # Fetch historical data for the trading pair
            ohlcv = self.exchange.fetch_ohlcv(self.trading_pair, timeframe=self.moving_average_timeframe, limit=period)
            close_prices = [x[4] for x in ohlcv]  # Extract closing prices

            # Calculate a simple moving average
            avg_price = sum(close_prices) / len(close_prices)

            # Compare the latest price to the average
            current_price = close_prices[-1]
            print(f"{self.trading_pair} - Current price: {current_price}, Moving average: {avg_price}", flush=True)
            return current_price < avg_price  # Downward trend if current price < average
        except Exception as e:
            print(f"Error detecting trend for {self.trading_pair}: {e}")
            return False


    def calculate_order_prices(self, current_price):
        """Calculate buy and sell prices based on current price and spread."""
        buy_price = current_price * (1 - self.spread_percentage)
        sell_price = current_price * (1 + self.spread_percentage)
        buy_price = float(self.exchange.price_to_precision(self.trading_pair, buy_price))
        sell_price = float(self.exchange.price_to_precision(self.trading_pair, sell_price))
        return buy_price, sell_price


    def place_buy_order(self, order_size, buy_price):
        """Place a buy order."""
        try:
            buy_order = self.exchange.create_limit_buy_order(self.trading_pair, order_size, buy_price)
            print(f"{self.trading_pair} - Buy order placed - Price: {buy_price:.6f} - Amount: {order_size:.6f}", flush=True)
            return buy_order
        except Exception as e:
            print(f"{self.trading_pair} - Error placing buy order: {e}", flush=True)
            return None


    def place_sell_order(self, order_size, sell_price):
        """Place a sell order."""
        try:
            sell_order = self.exchange.create_limit_sell_order(self.trading_pair, order_size, sell_price)
            print(f"{self.trading_pair} - Sell order placed - Price: {sell_price:.6f} - Amount: {order_size:.6f}", flush=True)
            return sell_order
        except Exception as e:
            print(f"{self.trading_pair} - Error placing sell order: {e}", flush=True)
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
                    print(f"{self.trading_pair} - Order {order['id']} already filled. Skipping adjustment.", flush=True)
                    continue

                # Cancel the order
                self.exchange.cancel_order(order['id'], self.trading_pair)
                print(f"{self.trading_pair} - Canceled order {order['id']}.", flush=True)
        except Exception as e:
            print(f"Error canceling open orders for {self.trading_pair}: {e}", flush=True)


    def adjust_orders(self):
        """
        Ensure both buy and sell orders are present, or adjust existing orders.
        Maintain at most one buy and one sell order at any time.
        """
        try:
            # Fetch open orders for the current trading pair
            open_orders = self.exchange.fetch_open_orders(self.trading_pair)

            # Separate existing buy and sell orders
            buy_order = None
            sell_order = None
            for order in open_orders:
                if order['side'] == 'buy':
                    if buy_order:  # Cancel any redundant buy orders
                        self.exchange.cancel_order(order['id'], self.trading_pair)
                        print(f"{self.trading_pair} - Canceled redundant buy order: {order['id']}", flush=True)
                    else:
                        buy_order = order
                elif order['side'] == 'sell':
                    if sell_order:  # Cancel any redundant sell orders
                        self.exchange.cancel_order(order['id'], self.trading_pair)
                        print(f"{self.trading_pair} - Canceled redundant sell order: {order['id']}", flush=True)
                    else:
                        sell_order = order

            # Fetch the current market price
            ticker = self.fetch_market_data()
            if not ticker:
                print(f"{self.trading_pair} - Failed to fetch market data.", flush=True)
                return

            current_price = ticker['last']
            buy_price, sell_price = self.calculate_order_prices(current_price)
            order_size = self.calculate_position_size()

            # Ensure sufficient balance for fixed trade value
            if self.available_balance < self.fixed_trade_value:
                print(f"{self.trading_pair} - Insufficient balance for trade. Available: {self.available_balance:.2f} USDT, Required: {self.fixed_trade_value:.2f}", flush=True)
                return

            # Manage buy order
            if not buy_order:
                print(f"{self.trading_pair} - No buy order found. Placing new buy order.", flush=True)
                self.place_buy_order(order_size, buy_price)
            else:
                if abs(buy_order['price'] - buy_price) > (current_price * 0.001):
                    self.exchange.cancel_order(buy_order['id'], self.trading_pair)
                    print(f"{self.trading_pair} - Adjusted buy order. New price: {buy_price:.6f}", flush=True)
                    self.place_buy_order(order_size, buy_price)

            # Manage sell order
            if not sell_order:
                print(f"{self.trading_pair} - No sell order found. Placing new sell order.", flush=True)
                self.place_sell_order(order_size, sell_price)
            else:
                if abs(sell_order['price'] - sell_price) > (current_price * 0.001):
                    self.exchange.cancel_order(sell_order['id'], self.trading_pair)
                    print(f"{self.trading_pair} - Adjusted sell order. New price: {sell_price:.6f}", flush=True)
                    self.place_sell_order(order_size, sell_price)

        except Exception as e:
            print(f"Error adjusting orders for {self.trading_pair}: {e}", flush=True)



    def market_making_strategy(self):
        """
        Core market-making logic that manages buy and sell orders.
        """
        if self.spread_percentage < 2 * self.trading_fee:
            raise ValueError(
                f"{self.trading_pair} - Spread percentage ({self.spread_percentage}) is too low to cover trading fees ({2 * self.trading_fee}%). Increase the spread."
            )

        while not self.stop_flag.is_set():
            try:
                print(f"{self.trading_pair} - Fetching market data...", flush=True)
                ticker = self.fetch_market_data()
                if not ticker:
                    print(f"{self.trading_pair} - Failed to fetch market data.", flush=True)
                    time.sleep(5)
                    continue

                current_price = ticker['last']
                print(f"{self.trading_pair} - Current price: {current_price:.6f}", flush=True)
                self.refresh_balance()

                # Handle downward trends with buy orders only
                while self.is_downward_trend():
                    print(f"{self.trading_pair} - Downward trend detected. Placing buy orders only.", flush=True)
                    self.cancel_all_open_orders()

                    buy_price, _ = self.calculate_order_prices(current_price)
                    order_size = self.calculate_position_size()

                    if self.available_balance >= self.fixed_trade_value:
                        self.place_buy_order(order_size, buy_price)
                        print(f"{self.trading_pair} - Buy order placed during downward trend.", flush=True)
                    else:
                        print(f"{self.trading_pair} - Insufficient balance for buy order during downward trend.", flush=True)

                    time.sleep(self.trade_interval)

                # Normal market-making mode
                self.adjust_orders()
                time.sleep(self.trade_interval)

            except Exception as e:
                print(f"Error executing market making strategy for {self.trading_pair}: {e}", flush=True)
                time.sleep(5)


    def run(self):
        self.market_making_strategy()


    def stop(self):
        self.stop_flag.set()  # Signal the bot to stop


if __name__ == "__main__":
    trading_pairs = os.getenv("TRADING_PAIRS", "ADA/USDT,CKB/USDT,BTC/USDT").split(",")
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