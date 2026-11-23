import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.monitoring.edge_requests import get_edge_request_rates, reset_edge_request_cache


def _line(host: str, when: datetime) -> str:
    return json.dumps({
        "StartUTC": when.isoformat().replace("+00:00", "Z"),
        "RequestHost": host,
        "RouterName": "router-" + host,
    })


def test_counts_requests_per_host_in_rolling_window(tmp_path: Path, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    log = tmp_path / "access.log"
    log.write_text("\n".join([
        _line("a.example", now - timedelta(seconds=5)),
        _line("a.example", now - timedelta(seconds=10)),
        _line("b.example", now - timedelta(seconds=8)),
        _line("a.example", now - timedelta(hours=2)),
    ]), encoding="utf-8")
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))
    reset_edge_request_cache()
    result = get_edge_request_rates(window_seconds=60)
    assert result.available is True
    assert round(result.rates_by_host["a.example"], 4) == round(2 / 60, 4)
    assert round(result.rates_by_host["b.example"], 4) == round(1 / 60, 4)


def test_unavailable_without_configured_log(monkeypatch) -> None:
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", "")
    reset_edge_request_cache()
    result = get_edge_request_rates()
    assert result.available is False
    assert result.rates_by_host == {}


def test_malformed_lines_are_ignored(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "access.log"
    log.write_text("not json\n" + _line("a.example", datetime.now(timezone.utc)) + "\n", encoding="utf-8")
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))
    reset_edge_request_cache()
    assert list(get_edge_request_rates().rates_by_host) == ["a.example"]
