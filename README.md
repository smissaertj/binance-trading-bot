# Binance Scalping Bot

```bash
cp .env.example .env
podman build -t binance_scalping_bot .
# The second part of the volume mount now points to /data
podman run --env-file ./.env \
       -v "$(pwd)/binance_scalping_bot_data:/data" \
       binance_scalping_bot
```

