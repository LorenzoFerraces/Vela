from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.logging.collector import (
    LogCollector,
    _int_setting,
    _split_log_timestamp,
    batch_insert_logs,
    cleanup_old_logs,
)
from app.db.base import Base
from app.db.models import ContainerLog, LogLevel, LogSource


def test_batch_insert_logs(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        logs = [
            ContainerLog(
                container_id="cid-1",
                container_name="test",
                timestamp=datetime.now(timezone.utc),
                source=LogSource.STDOUT,
                level=LogLevel.INFO,
                message="hello",
            ),
            ContainerLog(
                container_id="cid-2",
                container_name="test2",
                timestamp=datetime.now(timezone.utc),
                source=LogSource.STDERR,
                level=LogLevel.ERROR,
                message="fail",
            ),
        ]
        async with db_session_factory() as session:
            await batch_insert_logs(session, logs)
            result = await session.execute(
                select(ContainerLog)
            )
            rows = result.scalars().all()
            assert len(rows) == 2

    asyncio.run(run())


def test_batch_insert_logs_empty(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        async with db_session_factory() as session:
            await batch_insert_logs(session, [])
            result = await session.execute(
                select(ContainerLog)
            )
            rows = result.scalars().all()
            assert len(rows) == 0

    asyncio.run(run())


def test_cleanup_old_logs(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def run() -> None:
        now = datetime.now(timezone.utc)
        old_logs = [
            ContainerLog(
                container_id="cid-1",
                container_name="old",
                timestamp=now - timedelta(days=10),
                created_at=now - timedelta(days=10),
                source=LogSource.STDOUT,
                level=LogLevel.INFO,
                message="old log",
            ),
            ContainerLog(
                container_id="cid-1",
                container_name="old",
                timestamp=now - timedelta(days=8),
                created_at=now - timedelta(days=8),
                source=LogSource.STDOUT,
                level=LogLevel.WARN,
                message="also old",
            ),
        ]
        recent_logs = [
            ContainerLog(
                container_id="cid-2",
                container_name="recent",
                timestamp=now - timedelta(hours=1),
                created_at=now - timedelta(hours=1),
                source=LogSource.STDOUT,
                level=LogLevel.INFO,
                message="recent log",
            ),
        ]
        async with db_session_factory() as session:
            await batch_insert_logs(session, old_logs + recent_logs)

        async with db_session_factory() as session:
            deleted = await cleanup_old_logs(session, retention_days=7)
            assert deleted == 2

        async with db_session_factory() as session:
            result = await session.execute(
                select(ContainerLog)
            )
            rows = result.scalars().all()
            assert len(rows) == 1
            assert rows[0].message == "recent log"

    asyncio.run(run())


@dataclass
class _StubContainer:
    id: str
    name: str = "demo"
    status: str = "running"


class _StubClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StubOrchestrator:
    """Duck-typed orchestrator; the collector only calls .list() and .logs().

    Each line is stamped with the stub clock so `since` filtering is exact:
    a line is returned iff its timestamp is >= `since` (inclusive, like Docker).
    Lines are emitted with an RFC3339 prefix only when constructed with
    `timestamps=True` (and the line was added as prefixed).
    """

    def __init__(self, clock: _StubClock, timestamps: bool = False) -> None:
        self.clock = clock
        self.timestamps = timestamps
        self.lines: dict[str, list[tuple[float, str, bool]]] = {}
        self.log_calls: list[tuple[str, int | None, float | None]] = []

    def add(self, container_id: str, *lines: str, prefixed: bool = True) -> None:
        for line in lines:
            self.lines.setdefault(container_id, []).append(
                (self.clock.now, line, prefixed)
            )
            self.clock.advance(1.0)

    def restamp(self, container_id: str, ts: float) -> None:
        self.lines[container_id] = [
            (ts, line, prefixed) for ts, line, prefixed in self.lines[container_id]
        ]

    @staticmethod
    def _stamp(ts: float) -> str:
        return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%fZ"
        )

    async def list(self) -> list[_StubContainer]:
        return [_StubContainer(id=cid) for cid in self.lines]

    async def logs(
        self,
        container_id: str,
        *,
        tail: int | None = 100,
        since: float | None = None,
        timestamps: bool = False,
    ) -> str:
        self.log_calls.append((container_id, tail, since))
        entries = self.lines.get(container_id, [])
        if since is not None:
            entries = [entry for entry in entries if entry[0] >= since]
        if tail is not None:
            entries = entries[-tail:]
        parts = []
        for ts, line, prefixed in entries:
            if timestamps and self.timestamps and prefixed:
                parts.append(f"{self._stamp(ts)} {line}\n")
            else:
                parts.append(f"{line}\n")
        return "".join(parts)


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def setup() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    asyncio.run(setup())
    return factory


def _log_rows(factory: async_sessionmaker[AsyncSession]) -> list[ContainerLog]:
    async def run() -> list[ContainerLog]:
        async with factory() as session:
            result = await session.execute(select(ContainerLog))
            return list(result.scalars().all())

    return asyncio.run(run())


def _naive_utc(value: datetime) -> datetime:
    # ponytail: sqlite round-trips strip tzinfo (naive UTC wall time); Postgres returns aware
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def test_first_poll_seeds_without_insert() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock)
    orchestrator.add("c1", "l1", "l2", "l3", "l4", "l5")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        clock=clock,
    )

    async def run() -> None:
        await collector.poll_once()
        orchestrator.add("c1", "l6")
        await collector.poll_once()

    asyncio.run(run())
    rows = _log_rows(factory)
    assert [row.message for row in rows] == ["l6"]


def test_overlap_lines_are_deduplicated() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock)
    orchestrator.add("c1", "a", "b", "c")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        clock=clock,
    )

    async def run() -> None:
        await collector.poll_once()
        orchestrator.restamp("c1", clock.now)
        orchestrator.add("c1", "d")
        await collector.poll_once()

    asyncio.run(run())
    rows = _log_rows(factory)
    assert [row.message for row in rows] == ["d"]


def test_repeated_last_line_is_captured() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock)
    orchestrator.add("c1", "same")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        clock=clock,
    )

    async def run() -> None:
        await collector.poll_once()
        orchestrator.add("c1", "same")
        await collector.poll_once()
        orchestrator.add("c1", "same", "same")
        await collector.poll_once()
        orchestrator.add("c1", "same", "same", "same")
        await collector.poll_once()

    asyncio.run(run())
    rows = _log_rows(factory)
    assert len(rows) == 6
    assert {row.message for row in rows} == {"same"}


def test_gap_larger_than_window_inserts_everything() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock)
    orchestrator.add("c1", "seed")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        clock=clock,
    )

    async def run() -> None:
        await collector.poll_once()
        orchestrator.add("c1", *[f"gap-{n}" for n in range(1, 61)])
        await collector.poll_once()

    asyncio.run(run())
    rows = _log_rows(factory)
    assert len(rows) == 60
    assert {row.message for row in rows} == {f"gap-{n}" for n in range(1, 61)}


def test_since_cursor_is_passed() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock)
    orchestrator.add("c1", "x")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        clock=clock,
    )

    async def run() -> None:
        await collector.poll_once()
        orchestrator.add("c1", "y")
        await collector.poll_once()
        orchestrator.add("c1", "z")
        await collector.poll_once()

    asyncio.run(run())
    assert orchestrator.log_calls[0][2] is None
    first_cursor = orchestrator.log_calls[1][2]
    assert first_cursor is not None
    assert orchestrator.log_calls[2][2] is not None
    assert orchestrator.log_calls[2][2] > first_cursor


def test_disabled_does_nothing() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock)
    orchestrator.add("c1", "l1", "l2")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        enabled=False,
        clock=clock,
    )

    asyncio.run(collector.poll_once())
    assert _log_rows(factory) == []
    assert orchestrator.log_calls == []


def test_default_session_factory_inserts_logs(
    db_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch,
) -> None:
    """Production wiring passes no session_factory; the collector must resolve
    the module-level factory itself (regression: async_sessionmaker was used
    as an async context manager, TypeError on every poll)."""
    factory = db_session_factory
    monkeypatch.setattr(
        "app.core.logging.collector.get_session_factory", lambda: factory
    )
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock)
    orchestrator.add("c1", "l1")
    collector = LogCollector(orchestrator, poll_interval=0, clock=clock)

    async def run() -> None:
        await collector.poll_once()
        orchestrator.add("c1", "l2")
        await collector.poll_once()

    asyncio.run(run())
    assert [row.message for row in _log_rows(factory)] == ["l2"]


def test_split_log_timestamp_prefix() -> None:
    ts, message = _split_log_timestamp("2026-09-04T12:34:56.789012Z hello world")
    assert ts == datetime(2026, 9, 4, 12, 34, 56, 789012, tzinfo=timezone.utc)
    assert message == "hello world"

    ts, message = _split_log_timestamp("2026-09-04T14:34:56+02:00 offset line")
    assert ts == datetime(2026, 9, 4, 12, 34, 56, tzinfo=timezone.utc)
    assert message == "offset line"

    ts, message = _split_log_timestamp("2026-09-04T12:34:56.5Z short fraction")
    assert ts == datetime(2026, 9, 4, 12, 34, 56, 500000, tzinfo=timezone.utc)
    assert message == "short fraction"

    assert _split_log_timestamp("plain line without prefix") == (
        None,
        "plain line without prefix",
    )
    assert _split_log_timestamp("2026-09-04T12:34:56.987654321Z nine digits") == (
        datetime(2026, 9, 4, 12, 34, 56, 987654, tzinfo=timezone.utc),
        "nine digits",
    )
    assert _split_log_timestamp("2026-13-45T99:99:99Z not a date") == (
        None,
        "2026-13-45T99:99:99Z not a date",
    )
    assert _split_log_timestamp("2026-09-04T12:34:56Z") == (
        None,
        "2026-09-04T12:34:56Z",
    )


def test_prefixed_lines_use_line_timestamps() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock, timestamps=True)
    t0 = clock.now
    orchestrator.add("c1", "a", "b", "c")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        clock=clock,
    )

    async def run() -> None:
        await collector.poll_once()
        orchestrator.add("c1", "d")
        await collector.poll_once()

    asyncio.run(run())
    rows = _log_rows(factory)
    assert [row.message for row in rows] == ["d"]
    assert _naive_utc(rows[0].timestamp) == datetime.fromtimestamp(
        t0 + 3, tz=timezone.utc
    ).replace(tzinfo=None)
    assert orchestrator.log_calls[0][2] is None
    assert orchestrator.log_calls[1][2] == t0 + 2


def test_mixed_prefixed_and_unprefixed_lines() -> None:
    factory = _make_session_factory()
    clock = _StubClock()
    orchestrator = StubOrchestrator(clock, timestamps=True)
    t0 = clock.now
    orchestrator.add("c1", "seed")
    collector = LogCollector(
        orchestrator,
        session_factory=factory,
        poll_interval=0,
        max_lines_per_poll=50,
        clock=clock,
    )

    async def run() -> None:
        await collector.poll_once()
        orchestrator.add("c1", "p1")
        orchestrator.add("c1", "u1", prefixed=False)
        orchestrator.add("c1", "p2")
        await collector.poll_once()
        orchestrator.add("c1", "p3")
        await collector.poll_once()

    asyncio.run(run())
    rows = _log_rows(factory)
    assert [row.message for row in rows] == ["p1", "u1", "p2", "p3"]
    assert _naive_utc(rows[0].timestamp) == datetime.fromtimestamp(
        t0 + 1, tz=timezone.utc
    ).replace(tzinfo=None)
    assert _naive_utc(rows[2].timestamp) == datetime.fromtimestamp(
        t0 + 3, tz=timezone.utc
    ).replace(tzinfo=None)
    assert (
        abs(
            (_naive_utc(datetime.now(timezone.utc)) - _naive_utc(rows[1].timestamp))
            .total_seconds()
        )
        < 60
    )
    assert orchestrator.log_calls[2][2] == t0 + 3


def test_int_setting_falls_back_on_malformed_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VELA_LOG_BATCH_SIZE", "abc")
    assert _int_setting("VELA_LOG_BATCH_SIZE", 100) == 100
    monkeypatch.setenv("VELA_LOG_RETENTION_DAYS", "7d")
    assert _int_setting("VELA_LOG_RETENTION_DAYS", 7) == 7
    monkeypatch.delenv("VELA_LOG_BATCH_SIZE", raising=False)
    assert _int_setting("VELA_LOG_BATCH_SIZE", 100) == 100
    monkeypatch.setenv("VELA_LOG_BATCH_SIZE", "42")
    assert _int_setting("VELA_LOG_BATCH_SIZE", 100) == 42
