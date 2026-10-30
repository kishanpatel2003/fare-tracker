# Fare Tracker

A small daily flight-fare monitor: collect nonstop round-trip options, compare prices with the previous run, and send a compact Telegram update. Trip details live in a local JSON configuration rather than in the code.

## Offline demo

Install [uv](https://docs.astral.sh/uv/), then:

```sh
uv run tracker.py --config config.example.json --demo
```

The demo uses synthetic prices and makes no flight queries, sends no messages, and writes no history. Its example route and dates are fictional configuration, not a real itinerary.

## Track a trip

```sh
cp config.example.json config.json
cp .env.example .env
# Edit config.json with your route, future travel dates, and arrival cutoffs
uv run tracker.py --config config.json --dry-run
```

Python 3.11+ dependencies are declared inline and installed by uv. `--dry-run` fetches live fares and records local history, but prints the alert instead of sending it. Live retrieval depends on the upstream fast-flights package and may change or fail when its data source changes. Live fares were not verified as part of this public release.

For Telegram delivery, set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in local `.env` or the environment, then omit `--dry-run`. Create your own bot with BotFather and use its getUpdates response to find the destination chat ID. Neither value belongs in Git.

## Scheduling and data

`launchd.example.plist` is a macOS daily 09:00 template. Replace `__UV_PATH__` with the absolute result of `command -v uv`, replace `__PROJECT_DIR__` with the checkout path, create `logs/`, and save the edited file in `~/Library/LaunchAgents/` before loading it. Scheduling is opt-in; the demo does not install a job.

History is stored in ignored `history.json`. Configuration, credentials, and logs stay local. Use a separate checkout/history file for each trip so comparisons are between matching routes and dates.

## Checks

```sh
uv run --with pytest --with fast-flights --with requests --with typing_extensions python -m pytest -q
```

Tests use temporary files and fake data; they do not retrieve fares or send notifications.

MIT; see [LICENSE](LICENSE)
