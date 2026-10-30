# Fare Tracker

Track nonstop round-trip fares, compare prices with the previous run, and send a compact Telegram update. Configure the route, dates, passengers, and arrival cutoffs in JSON.

## Getting started

Install [uv](https://docs.astral.sh/uv/), then:

```sh
cp config.example.json config.json
cp .env.example .env
# Edit config.json with your route and travel dates
uv run tracker.py --config config.json --dry-run
```

Python 3.11+ dependencies are declared inline and installed by uv. `--dry-run` retrieves fares and records local history, then prints the update instead of sending it. Retrieval uses fast-flights.

To preview the output with example prices:

```sh
uv run tracker.py --config config.example.json --example
```

This mode uses example prices without retrieving fares, sending messages, or changing history.

## Telegram

Set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in local `.env` or the environment, then omit `--dry-run`. Create a bot with BotFather and use its getUpdates response to find the destination chat ID.

## Scheduling and data

`launchd.example.plist` runs daily at 09:00 on macOS. Replace `__UV_PATH__` with the absolute result of `command -v uv`, replace `__PROJECT_DIR__` with the checkout path, create `logs/`, and save the edited file in `~/Library/LaunchAgents/` before loading it.

History lives in `history.json`; configuration, credentials, history, and logs are ignored by Git. Use a separate checkout/history file per trip so price comparisons use matching routes and dates.

## Checks

```sh
uv run --with pytest --with fast-flights --with requests --with typing_extensions python -m pytest -q
```

[MIT](LICENSE)
