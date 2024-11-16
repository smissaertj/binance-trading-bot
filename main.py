import ccxt
import os
import threading
import time


class TradingBot:
    def __init__(self, trading_pair, strategy='scalping'):
        # Load parameters from environment variables or use defaults
        self.api_key = os.getenv("API_KEY")
        self.api_secret = os.getenv("API_SECRET")
        self.trading_fee = float(os.getenv("TRADING_FEE", 0.001))  # Default Binance 0.1% Spot Trading fee
        self.stop_loss = float(os.getenv("SCALP_STOP_LOSS_PERCENTAGE", 0.015))  # Scalping, Default 1.5%
        self.profit_target = float(os.getenv("SCALP_PROFIT_TARGET_PERCENTAGE", 0.005))  # Scalping, Default 0.5%
        self.percentage_of_balance = float(os.getenv("SCALP_PERCENTAGE_OF_BALANCE", 0.05))  # Scalping, Default 5%
        self.spread_percentage = float(os.getenv("MM_SPREAD_PERCENTAGE", 0.03))  # Market Making, Default 3%
        self.order_size = float(os.getenv("MM_ORDER_SIZE", 0))  # Default: Dynamically calculated if not set
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
        self.strategy = strategy
        self.position_size = 0  # To store position size for buy/sell consistency
        self.available_balance = 0  # Keep track of remaining base currency amount

        # Load markets to fetch trading pair metadata
        print("Loading Binance markets...", flush=True)
        self.exchange.load_markets()
        print("Markets loaded successfully.", flush=True)

        # Validate and adjust order size at initialization
        if self.order_size > 0:  # Only validate if explicitly configured
            min_order_size = self.get_minimum_order_size()
            if self.order_size < min_order_size:
                print(f"Warning: Provided order size {self.order_size} is below minimum order size {min_order_size}. Adjusting to minimum.", flush=True)
                self.order_size = min_order_size


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
            quote_currency = self.trading_pair.split('/')[1]  # Extract quote currency, e.g., 'USDT'
            self.available_balance = balance[quote_currency]['free']
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
            balance = self.exchange.fetch_balance()
            quote_currency = self.trading_pair.split('/')[1]  # Extract quote currency, e.g., 'USDT'
            self.available_balance = balance[quote_currency]['free']  # Available balance in quote currency

            # Fetch the current price of the trading pair
            ticker = self.fetch_market_data()
            if not ticker:
                raise ValueError(f"Could not fetch {self.trading_pair} market data for position size calculation.")
            current_price = ticker['last']

            # Calculate position size for buy orders
            position_size = (self.available_balance * self.percentage_of_balance) / current_price
            print(f"[{self.trading_pair}] Available Balance: {self.available_balance:.2f} {quote_currency}, Position Size: {position_size:.6f}", flush=True)
            return position_size
        except Exception as e:
            print(f"Error calculating position size for {self.trading_pair}: {e}", flush=True)
            return 0


    def scalping_strategy(self):
        while not self.stop_flag.is_set():  # Check stop flag: # Keep trading continuously
            ticker = self.fetch_market_data()
            if ticker:
                entry_price = ticker['last']
                stop_loss_price = entry_price * (1 - self.stop_loss)
                target_price = entry_price * (1 + self.profit_target)

                # Calculate position size
                self.position_size = self.calculate_position_size()
                if self.position_size <= 0:
                    print(f"Invalid position size for {self.trading_pair}. Skipping trade.", flush=True)
                    return

                print(f"Scalping - {self.trading_pair} - Entry Price: {entry_price}, Target Price: {target_price}, Stop Loss: {stop_loss_price}, Position Size: {self.position_size}", flush=True)

                try:
                    # Place a buy order
                    buy_order = self.exchange.create_market_buy_order(self.trading_pair, self.position_size)

                    # Extract the price at which the order was executed
                    executed_price = buy_order.get('price')
                    if not executed_price or executed_price == 0:
                        executed_price = buy_order['cost'] / buy_order['filled'] if buy_order['filled'] > 0 else None

                    # Amount bought in base currency
                    amount_bought = buy_order.get('filled', 0)  # `filled` indicates how much of the base currency was purchased
                    # Total cost in quote currency
                    total_cost = buy_order.get('cost', 0)  # `cost` indicates the total spent in the quote currency

                    # Refresh balance after buy order
                    self.refresh_balance()

                    if executed_price:
                        print(f"Scalping - {self.trading_pair} - Buy order placed - Order ID {buy_order['id']} - "
                              f"Executed Price: {executed_price} - Crypto amount Bought: {amount_bought} - USDT Cost: {total_cost} "
                              f"- USDT Balance: {self.available_balance}", flush=True)
                    else:
                        print(f"Scalping - {self.trading_pair} - Buy order placed - Order ID {buy_order['id']} - "
                              f"Executed Price: Unknown - Crypto Amount Bought: {amount_bought} - USDT Cost: {total_cost} "
                              f"- USDT Balance: {self.available_balance}", flush=True)

                    # Monitor price for target or stop-loss
                    while True:
                        current_price = self.fetch_market_data()['last']
                        if current_price >= target_price:
                            # Place a sell order to take profit
                            sell_order = self.exchange.create_market_sell_order(self.trading_pair, self.position_size)
                            # Refresh balance after sell order
                            self.refresh_balance()
                            print(f"Scalping - {self.trading_pair} - Sell order placed at target {target_price} - Order ID {sell_order['id']} - USDT Balance: {self.available_balance}", flush=True)
                            break
                        elif current_price <= stop_loss_price:
                            # Place a sell order to stop loss
                            sell_order = self.exchange.create_market_sell_order(self.trading_pair, self.position_size)
                            # Refresh balance after sell order
                            self.refresh_balance()
                            print(f"Scalping - {self.trading_pair} - Stop Loss triggered at {stop_loss_price} - Order ID {sell_order['id']} - USDT Balance: {self.available_balance}", flush=True)
                            break
                        time.sleep(5)  # Adjust based on desired frequency
                except Exception as e:
                    print(f"Error executing scalping strategy: {e}", flush=True)

                # Pause briefly before starting the next cycle
                print(f"Scalping - {self.trading_pair} - Cycle complete. Restarting...")
                time.sleep(60)


    def market_making_strategy(self):
        if self.spread_percentage < 2 * self.trading_fee:
            raise ValueError(f"Spread percentage ({self.spread_percentage}) is too low to cover trading fees ({2 * self.trading_fee}%). Increase the spread.")

        while not self.stop_flag.is_set():
            try:
                print(f"Market making - {self.trading_pair} - Fetching market data...")
                ticker = self.fetch_market_data()
                if not ticker:
                    print(f"Market making - {self.trading_pair} - Failed to fetch market data.")
                    time.sleep(5)
                    continue

                current_price = ticker['last']
                print(f"Market making - {self.trading_pair} - Current price: {current_price:.6f}")

                # Fetch market limits
                min_notional = self.get_minimum_notional()
                min_order_size = self.get_minimum_order_size()

                # Calculate limit order prices adjusted for fees
                buy_price = current_price * (1 - self.spread_percentage - self.trading_fee)
                sell_price = current_price * (1 + self.spread_percentage + self.trading_fee)
                print(f"Market making - {self.trading_pair} - Buy price: {buy_price:.6f}, Sell price: {sell_price:.6f}")

                # Calculate dynamic order size
                order_size = self.order_size if self.order_size > 0 else self.available_balance * self.percentage_of_balance / current_price

                # Adjust for minimum order size
                if order_size < min_order_size:
                    order_size = min_order_size
                    print(f"Adjusted order size to meet minimum order size: {order_size:.6f}")

                # Adjust for minimum notional value
                notional_value = order_size * buy_price
                if notional_value < min_notional:
                    print(f"Final notional value {notional_value:.6f} is still below the minimum of {min_notional}. Adjusting further...")
                    # Add a small buffer to ensure the adjusted size exceeds the minimum notional
                    buffer = 10 ** -self.exchange.markets[self.trading_pair]['precision']['amount']
                    order_size = (min_notional / buy_price) + buffer
                    order_size = float(self.exchange.amount_to_precision(self.trading_pair, order_size))
                    print(f"Final adjusted order size to meet notional after precision: {order_size:.6f}")

                # Enforce precision
                order_size = float(self.exchange.amount_to_precision(self.trading_pair, order_size))
                print(f"Final adjusted order size after precision: {order_size}")

                # Recalculate notional value after enforcing precision
                notional_value = order_size * buy_price
                if notional_value < min_notional:
                    print(f"Final notional value {notional_value:.6f} is still below the minimum of {min_notional}. Adjusting further...")
                    order_size = (min_notional / buy_price) + (10 ** -self.exchange.markets[self.trading_pair]['precision']['amount'])
                    order_size = float(self.exchange.amount_to_precision(self.trading_pair, order_size))
                    print(f"Final adjusted order size to meet notional after precision: {order_size:.6f}")

                # Place limit buy order
                buy_order = self.exchange.create_limit_buy_order(self.trading_pair, order_size, buy_price)
                print(f"Market making - {self.trading_pair} - Buy order placed - Price: {buy_order['price']} - Amount: {buy_order['amount']}")

                # Place limit sell order
                sell_order = self.exchange.create_limit_sell_order(self.trading_pair, order_size, sell_price)
                print(f"Market making - {self.trading_pair} - Sell order placed - Price: {sell_order['price']} - Amount: {sell_order['amount']}")

                # Monitor orders for execution or adjust prices dynamically
                time.sleep(60)  # TODO - Adjust the time to wait before checking if an order has been filled.

                buy_order_status = self.exchange.fetch_order(buy_order['id'], self.trading_pair)
                filled_buy = buy_order_status['status'] == 'closed'  # 'closed' means the order was filled
                if filled_buy:
                    print(f"Market making - {self.trading_pair} - Buy order {buy_order['id']} was filled successfully.")
                else:
                    self.exchange.cancel_order(buy_order['id'], self.trading_pair)
                    print(f"Market making - {self.trading_pair} - Buy order {buy_order['id']} unfilled, canceled and will be adjusted.")

                sell_order_status = self.exchange.fetch_order(sell_order['id'], self.trading_pair)
                filled_sell = sell_order_status['status'] == 'closed'  # 'closed' means the order was filled
                if filled_sell:
                    print(f"Market making - {self.trading_pair} - Sell order {sell_order['id']} was filled successfully.")
                else:
                    self.exchange.cancel_order(sell_order['id'], self.trading_pair)
                    print(f"Market making - {self.trading_pair} - Sell order {sell_order['id']} unfilled, canceled and will be adjusted.")

            except Exception as e:
                print(f"Error executing market making strategy for {self.trading_pair}: {e}")
                time.sleep(5)


    def run(self):
        if self.strategy == 'market_making':
            self.market_making_strategy()
        elif self.strategy == 'scalping':
            self.scalping_strategy()
        else:
            print("Invalid strategy selected", flush=True)


    def stop(self):
        self.stop_flag.set()  # Signal the bot to stop


if __name__ == "__main__":
    strat = os.getenv("STRATEGY", "market_making") # One of ["scalping", "market_making"]
    trading_pairs = os.getenv("TRADING_PAIRS", "ADA/USDT,CKB/USDT").split(",")
    bots = []

    # Start bots
    for i, pair in enumerate(trading_pairs):
        bot = TradingBot(trading_pair=pair, strategy=strat)
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