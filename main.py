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
        self.spread_percentage = float(os.getenv("MM_SPREAD_PERCENTAGE", 0.002))  # Market Making, Default 0.2%
        self.order_size = float(os.getenv("MM_ORDER_SIZE", 0.05))  # Market Making, Default 5% of the base currency balance

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

        self.exchange.set_sandbox_mode(sandbox_mode)
        self.trading_pair = trading_pair
        self.strategy = strategy
        self.position_size = 0  # To store position size for buy/sell consistency
        self.available_balance = 0  # Keep track of remaining base currency amount

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
                time.sleep(5)


    def market_making_strategy(self):
        if self.spread_percentage < 2 * self.trading_fee:
            raise ValueError(f"Spread percentage ({self.spread_percentage}) is too low to cover trading fees of ({2 * self.trading_fee}%). Increase the spread.")

        while not self.stop_flag.is_set():
            try:
                # Fetch current market price
                ticker = self.fetch_market_data()
                if not ticker:
                    print(f"Market making - {self.trading_pair} - Failed to fetch market data.", flush=True)
                    time.sleep(5)
                    continue

                current_price = ticker['last']

                # Calculate limit order prices adjusted for fees
                buy_price = current_price * (1 - self.spread_percentage - self.trading_fee)
                sell_price = current_price * (1 + self.spread_percentage + self.trading_fee)

                # Determine the oder size dynamically
                order_size = self.order_size if self.order_size else self.available_balance * self.percentage_of_balance / current_price

                # Place limit buy order
                buy_order = self.exchange.create_limit_buy_order(self.trading_pair, order_size, buy_price)

                # Calculate fee and effective amount bought
                buy_fee = order_size * buy_price * self.trading_fee
                effective_buy = order_size * (1 - self.trading_fee)

                print(f"Market making - {self.trading_pair} - Buy order placed: Price {buy_price:.6f} - "
                      f"Size {order_size} - Fee: {buy_fee:.6f} - Effective Bought: {effective_buy:.6f}", flush=True)

                # Place limit sell order
                sell_order = self.exchange.create_limit_sell_order(self.trading_pair, order_size, sell_price)

                # Calculate fee and effective proceeds
                sell_fee = order_size * sell_price * self.trading_fee
                effective_sell = order_size * sell_price * (1 - self.trading_fee)

                print(f"Market making - {self.trading_pair} - Sell order placed: Price {sell_price:.6f} - "
                      f"Size {order_size} - Fee: {sell_fee:.6f} - Effective Proceeds: {effective_sell:.6f}", flush=True)

                # Monitor and adjust orders
                time.sleep(10)  # Adjust frequency as needed

                # Cancel unfilled orders and refresh
                self.exchange.cancel_order(buy_order['id'], self.trading_pair)
                self.exchange.cancel_order(sell_order['id'], self.trading_pair)
                print(f"Market making - {self.trading_pair} - Cancelled unfilled orders.", flush=True)

            except Exception as e:
                print(f"Error executing market making strategy for {self.trading_pair}: {e}", flush=True)
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
    for pair in trading_pairs:
        bot = TradingBot(trading_pair=pair, strategy=strat)
        thread = threading.Thread(target=bot.run)
        bots.append((bot, thread))
        thread.start()

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