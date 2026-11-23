import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import app.core.monitoring.edge_requests as edge_requests
from app.core.monitoring.edge_requests import get_edge_request_rates, reset_edge_request_cache


def _line(host: str, when: datetime) -> str:
    return json.dumps({
        "StartUTC": when.isoformat().replace("+00:00", "Z"),
        "RequestHost": host,
        "RouterName": "router-" + host,
    })


@pytest.fixture(autouse=True)
def _no_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    # Recompute on every call so tailing behaviour can be asserted directly.
    monkeypatch.setattr(edge_requests, "_CACHE_TTL_SECONDS", 0)
    reset_edge_request_cache()


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


def test_unreadable_log_is_unavailable_not_zero_traffic(
    tmp_path: Path, monkeypatch, caplog
) -> None:
    missing = tmp_path / "missing.log"
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(missing))
    reset_edge_request_cache()
    with caplog.at_level("WARNING"):
        result = get_edge_request_rates()
    assert result.available is False
    assert result.rates_by_host == {}
    assert "Cannot read edge access log" in caplog.text


def test_malformed_lines_are_ignored(tmp_path: Path, monkeypatch) -> None:
    log = tmp_path / "access.log"
    log.write_text("not json\n" + _line("a.example", datetime.now(timezone.utc)) + "\n", encoding="utf-8")
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))
    reset_edge_request_cache()
    assert list(get_edge_request_rates().rates_by_host) == ["a.example"]


def test_incremental_tail_counts_only_appended_lines(
    tmp_path: Path, monkeypatch
) -> None:
    now = datetime.now(timezone.utc)
    log = tmp_path / "access.log"
    log.write_text(_line("a.example", now) + "\n", encoding="utf-8")
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))

    first = get_edge_request_rates(window_seconds=60)
    assert round(first.rates_by_host["a.example"], 4) == round(1 / 60, 4)

    with log.open("a", encoding="utf-8") as handle:
        handle.write(_line("b.example", now) + "\n")
    second = get_edge_request_rates(window_seconds=60)
    # The first line was not reparsed, but its event is still inside the window.
    assert second.rates_by_host == {
        "a.example": pytest.approx(1 / 60),
        "b.example": pytest.approx(1 / 60),
    }


def test_truncated_log_resets_and_reparses(tmp_path: Path, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    log = tmp_path / "access.log"
    log.write_text(
        _line("a.example", now) + "\n" + _line("a.example", now) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("VELA_EDGE_ACCESS_LOG_PATH", str(log))
    first = get_edge_request_rates(window_seconds=60)
    assert round(first.rates_by_host["a.example"], 4) == round(2 / 60, 4)

    # Rotation/truncation leaves the file smaller than the cached offset.
    log.write_text(_line("b.example", now) + "\n", encoding="utf-8")
    second = get_edge_request_rates(window_seconds=60)
    assert second.rates_by_host == {"b.example": pytest.approx(1 / 60)}
