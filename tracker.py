# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "fast-flights",
#   "typing_extensions",
#   "requests",
# ]
# ///

from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests
from fast_flights import Passengers, create_query, get_flights
from fast_flights.querying import FlightQuery
from typing_extensions import TypedDict


CONFIG: dict[str, Any] = {}
SCRIPT_DIR = Path(__file__).resolve().parent
HISTORY_PATH = SCRIPT_DIR / "history.json"
ENV_PATH = SCRIPT_DIR / ".env"
TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"


def google_flights_link() -> str:
    query = (
        f"Flights from {CONFIG['from_airport']} to {CONFIG['to_airport']} "
        f"on {CONFIG['outbound_date']} through {CONFIG['return_date']}"
    )
    return "https://www.google.com/travel/flights?q=" + quote(query, safe="")


def load_config(path: Path) -> dict[str, Any]:
    config = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "from_airport", "to_airport", "outbound_date", "return_date",
        "adults", "seat", "currency", "preferred_airline",
        "outbound_arrive_before", "return_land_before",
    }
    missing = required - set(config)
    if missing:
        raise ValueError("Missing config fields: " + ", ".join(sorted(missing)))
    for key in ("from_airport", "to_airport"):
        value = config[key]
        if not isinstance(value, str) or len(value) != 3 or not value.isalpha():
            raise ValueError(f"{key} must be a three-letter airport code")
        config[key] = value.upper()
    if type(config["adults"]) is not int or config["adults"] < 1:
        raise ValueError("adults must be a positive integer")
    outbound = date.fromisoformat(config["outbound_date"])
    returning = date.fromisoformat(config["return_date"])
    if returning < outbound:
        raise ValueError("return_date must not precede outbound_date")
    for key in ("outbound_arrive_before", "return_land_before"):
        hour, minute = map(int, config[key].split(":"))
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError(f"{key} must be HH:MM in 24-hour time")
        config[key] = (hour, minute)
    return config



class FlightRecord(TypedDict):
    key: str
    airline: str
    dep: str
    arr: str
    price: int


class HistoryRecord(TypedDict):
    date: str
    flights: list[FlightRecord]
    cheapest: int | None
    cheapest_united: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Track configurable round-trip fares.")
    parser.add_argument("--config", type=Path, default=SCRIPT_DIR / "config.json")
    parser.add_argument("--example", "--demo", dest="demo", action="store_true", help="Preview example fares offline without notifications or history writes.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the message instead of sending it to Telegram.",
    )
    return parser.parse_args()


def load_dotenv(path: Path = ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


def credentials() -> tuple[str | None, str | None]:
    env_file = load_dotenv()
    token = os.environ.get("TELEGRAM_BOT_TOKEN") or env_file.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID") or env_file.get("TELEGRAM_CHAT_ID")
    return token, chat_id


def simple_time(value: Any) -> tuple[int, int]:
    hour = int(value.time[0])
    minute = int(value.time[1]) if len(value.time) > 1 else 0
    return hour, minute


def time_before(value: Any, cutoff: tuple[int, int]) -> bool:
    return simple_time(value) < cutoff


def format_time(value: Any) -> str:
    hour, minute = simple_time(value)
    suffix = "a" if hour < 12 else "p"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d}{suffix}"


def money(value: int | None) -> str:
    return "n/a" if value is None else f"${value:,}"


def airline_name(airlines: list[str]) -> str:
    return " / ".join(airlines) if airlines else "Unknown"


def is_united(airline: str) -> bool:
    return CONFIG["preferred_airline"].lower() in airline.lower()


def display_airline(airline: str) -> str:
    return f"★ {airline}" if is_united(airline) else airline


def percent_delta(current: int | None, prior: int | None) -> float | None:
    if current is None or prior in (None, 0):
        return None
    return ((current - prior) / prior) * 100


def format_delta(delta: float | None, *, first_run: bool = False) -> str:
    if first_run:
        return "no prior data"
    if delta is None:
        return "— new"
    if delta < 0:
        return f"▼{abs(delta):.1f}%"
    if delta > 0:
        return f"▲{delta:.1f}%"
    return "0.0%"


def retry(label: str, fn: Any) -> Any:
    last_error: Exception | None = None
    for attempt in range(1, 4):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - failure is surfaced in alert.
            last_error = exc
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError(f"{label} failed after 3 attempts: {last_error}") from last_error


def fetch_round_trip_options() -> list[Any]:
    query = create_query(
        flights=[
            FlightQuery(
                date=CONFIG["outbound_date"],
                from_airport=CONFIG["from_airport"],
                to_airport=CONFIG["to_airport"],
            ),
            FlightQuery(
                date=CONFIG["return_date"],
                from_airport=CONFIG["to_airport"],
                to_airport=CONFIG["from_airport"],
            ),
        ],
        trip="round-trip",
        seat=CONFIG["seat"],
        passengers=Passengers(adults=CONFIG["adults"]),
        max_stops=0,
        currency=CONFIG["currency"],
    )
    return list(get_flights(query))


def fetch_return_options() -> list[Any]:
    query = create_query(
        flights=[
            FlightQuery(
                date=CONFIG["return_date"],
                from_airport=CONFIG["to_airport"],
                to_airport=CONFIG["from_airport"],
            )
        ],
        trip="one-way",
        seat=CONFIG["seat"],
        passengers=Passengers(adults=CONFIG["adults"]),
        max_stops=0,
        currency=CONFIG["currency"],
    )
    return list(get_flights(query))


def flight_sort_key(record: FlightRecord) -> tuple[int, int, str]:
    return (
        0 if is_united(record["airline"]) else 1,
        record["price"],
        record["dep"],
    )


def qualifying_flights(options: list[Any]) -> list[FlightRecord]:
    records: list[FlightRecord] = []
    for option in options:
        if not option.flights:
            continue
        outbound = option.flights[0]
        if not time_before(outbound.arrival, CONFIG["outbound_arrive_before"]):
            continue

        airline = airline_name(list(option.airlines))
        dep = format_time(outbound.departure)
        arr = format_time(outbound.arrival)
        records.append(
            {
                "key": f"{airline} {dep}",
                "airline": airline,
                "dep": dep,
                "arr": arr,
                "price": int(option.price),
            }
        )
    return sorted(records, key=flight_sort_key)


def qualifying_returns(options: list[Any]) -> list[str]:
    rows: list[tuple[int, str]] = []
    for option in options:
        if not option.flights:
            continue
        return_flight = option.flights[0]
        if not time_before(return_flight.arrival, CONFIG["return_land_before"]):
            continue

        airline = airline_name(list(option.airlines))
        dep = format_time(return_flight.departure)
        arr = format_time(return_flight.arrival)
        duration = getattr(return_flight, "duration", None)
        plane_type = getattr(return_flight, "plane_type", None)
        details = " · ".join(
            str(part) for part in (duration_text(duration), plane_type) if part
        )
        row = f"{display_airline(airline)} {dep} → {arr}"
        if details:
            row = f"{row} · {details}"
        dep_hour, dep_minute = simple_time(return_flight.departure)
        rows.append((dep_hour * 60 + dep_minute, row))
    return [row for _, row in sorted(rows)]


def duration_text(minutes: int | None) -> str | None:
    if minutes is None:
        return None
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h {mins}m"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def load_history() -> list[HistoryRecord]:
    if not HISTORY_PATH.exists():
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def write_history(history: list[HistoryRecord]) -> None:
    HISTORY_PATH.write_text(
        json.dumps(history, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def cheapest(records: list[FlightRecord]) -> int | None:
    return min((record["price"] for record in records), default=None)


def cheapest_united(records: list[FlightRecord]) -> int | None:
    return min(
        (record["price"] for record in records if is_united(record["airline"])),
        default=None,
    )


def append_history(
    records: list[FlightRecord],
) -> tuple[HistoryRecord, HistoryRecord | None]:
    history = load_history()
    prior = history[-1] if history else None
    current: HistoryRecord = {
        "date": date.today().isoformat(),
        "flights": records,
        "cheapest": cheapest(records),
        "cheapest_united": cheapest_united(records),
    }
    history.append(current)
    write_history(history)
    return current, prior


def build_message(
    current: HistoryRecord,
    prior: HistoryRecord | None,
    return_rows: list[str],
) -> str:
    first_run = prior is None
    prior_flights = (
        {record["key"]: record for record in prior["flights"]} if prior else {}
    )
    cheapest_delta = percent_delta(
        current["cheapest"],
        prior["cheapest"] if prior else None,
    )
    cheapest_delta_text = format_delta(cheapest_delta, first_run=first_run)
    if not first_run and cheapest_delta is not None:
        cheapest_delta_text = f"{cheapest_delta_text} vs yesterday"

    lines = [
        f"✈️ {CONFIG['from_airport']}→{CONFIG['to_airport']} "
        f"{CONFIG['outbound_date']}–{CONFIG['return_date']} · {CONFIG['adults']} pax RT",
        f"Cheapest: {money(current['cheapest'])} ({cheapest_delta_text})",
        "",
    ]

    if current["flights"]:
        for record in current["flights"]:
            prior_record = prior_flights.get(record["key"])
            delta = percent_delta(
                record["price"],
                prior_record["price"] if prior_record else None,
            )
            delta_text = format_delta(delta, first_run=False if prior else True)
            if first_run:
                delta_text = "no prior data"
            lines.append(
                f"{display_airline(record['airline'])} "
                f"{record['dep']} → {record['arr']}  "
                f"{money(record['price'])}  {delta_text}"
            )
    else:
        lines.append("No qualifying outbound flights found.")

    hour, minute = CONFIG["return_land_before"]
    lines.extend(["", f"Return options {CONFIG['return_date']} (land <{hour:02d}:{minute:02d}):"])
    if return_rows:
        lines.extend(return_rows)
    else:
        lines.append("No qualifying return flights found.")

    lines.extend(
        ["", f'Google Flights: <a href="{google_flights_link()}">open search</a>']
    )
    return "\n".join(
        html.escape(line, quote=False) if "<a href=" not in line else line
        for line in lines
    )


def send_telegram(message: str, *, dry_run: bool) -> None:
    token, chat_id = credentials()
    if dry_run or not token or not chat_id:
        print(message)
        return

    response = requests.post(
        TELEGRAM_API.format(token=token),
        data={
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": "true",
        },
        timeout=30,
    )
    response.raise_for_status()


def safe_error(error: Exception) -> str:
    message = str(error)
    token, _ = credentials()
    if token:
        message = message.replace(token, "[REDACTED]")
    return re.sub(r"https://api\.telegram\.org/bot[^/\s]+", "https://api.telegram.org/bot[REDACTED]", message)


def failure_message(error: Exception) -> str:
    return f"⚠️ Fare tracker failed: {html.escape(safe_error(error), quote=False)}"


def main() -> int:
    args = parse_args()
    try:
        CONFIG.update(load_config(args.config))
        if args.demo:
            sample = {"date": date.today().isoformat(), "flights": [
                {"key": "Example Air 10:00a", "airline": "Example Air", "dep": "10:00a", "arr": "1:00p", "price": 250}
            ], "cheapest": 250, "cheapest_united": None}
            print("Example fares")
            print(build_message(sample, None, ["Example Air 2:00p → 10:00p"]))
            return 0
        round_trip_options = retry("round-trip fetch", fetch_round_trip_options)
        return_options = retry("return fetch", fetch_return_options)
        records = qualifying_flights(round_trip_options)
        return_rows = qualifying_returns(return_options)
        current, prior = append_history(records)
        send_telegram(build_message(current, prior, return_rows), dry_run=args.dry_run)
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level alert path.
        try:
            send_telegram(failure_message(exc), dry_run=args.dry_run)
        except Exception as alert_exc:  # noqa: BLE001 - avoid hiding original failure.
            print(failure_message(exc))
            print(f"Telegram alert failed: {safe_error(alert_exc)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
