# Binance Trading Bot

## Introduction
The Binance Trading Bot is a containerized Python application that automates cryptocurrency trading using
the CCXT library. It supports scalping strategies, dynamic position sizing, 
and risk management through configurable stop-loss and profit target parameters. 
Designed for Podman and cloud deployment, it allows trading multiple pairs concurrently 
with secure environment variable configurations.

## Build the image
```bash
podman build -t binance-trading-bot .
```

## Run the container
```bash
podman run -it --rm \
    -e API_KEY="your_api_key" \
    -e API_SECRET="your_api_secret" \
    -e STOP_LOSS_PERCENTAGE="0.015" \
    -e PROFIT_TARGET_PERCENTAGE="0.005" \
    -e PERCENTAGE_OF_BALANCE="0.05" \
    -e TRADING_PAIRS="ADA/USDT,CKB/USDT" \
    -e SANDBOX_MODE="True" \
    --name ada-ckb-usdt-trading-bot \
    binance-trading-bot
```