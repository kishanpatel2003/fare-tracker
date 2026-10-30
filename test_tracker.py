import json
from pathlib import Path
import pytest
import tracker


def config_file(tmp_path, **changes):
    data = json.loads((Path(__file__).parent / "config.example.json").read_text())
    data.update(changes)
    path = tmp_path / "config.json"
    path.write_text(json.dumps(data))
    return path


def test_config_and_message_use_requested_route(tmp_path):
    config = tracker.load_config(config_file(tmp_path, from_airport="bos", to_airport="SFO", adults=2))
    tracker.CONFIG.clear()
    tracker.CONFIG.update(config)
    message = tracker.build_message({"date": "2030-06-01", "flights": [], "cheapest": None, "cheapest_united": None}, None, [])
    assert "BOS→SFO" in message and "2 pax" in message
    assert "BOS" in tracker.google_flights_link()
    assert config["return_land_before"] == (23, 59)


def test_rejects_reversed_dates(tmp_path):
    with pytest.raises(ValueError):
        tracker.load_config(config_file(tmp_path, return_date="2030-06-01"))


def test_rejects_invalid_cutoff(tmp_path):
    with pytest.raises(ValueError):
        tracker.load_config(config_file(tmp_path, return_land_before="25:00"))


def test_rejects_missing_fields(tmp_path):
    path = tmp_path / "config.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Missing config fields"):
        tracker.load_config(path)


def test_demo_does_not_fetch_send_or_write(tmp_path, monkeypatch, capsys):
    path = config_file(tmp_path)
    monkeypatch.setattr("sys.argv", ["tracker.py", "--config", str(path), "--demo"])
    def forbidden(*args, **kwargs):
        raise AssertionError("Demo attempted a live or persistent action")
    for name in ("fetch_round_trip_options", "fetch_return_options", "send_telegram", "write_history"):
        monkeypatch.setattr(tracker, name, forbidden)
    assert tracker.main() == 0
    assert "Example fares" in capsys.readouterr().out


def test_error_messages_do_not_expose_telegram_credentials(monkeypatch):
    monkeypatch.setattr(tracker, "credentials", lambda: ("synthetic-bot-credential", "demo-chat"))
    error = RuntimeError("request failed at https://api.telegram.org/botsynthetic-bot-credential/sendMessage")
    output = tracker.failure_message(error)
    assert "synthetic-bot-credential" not in output
    assert "REDACTED" in output
