import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.logging.collector import LogCollector, batch_insert_logs, cleanup_old_logs
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
    """

    def __init__(self, clock: _StubClock) -> None:
        self.clock = clock
        self.lines: dict[str, list[tuple[float, str]]] = {}
        self.log_calls: list[tuple[str, int | None, float | None]] = []

    def add(self, container_id: str, *lines: str) -> None:
        for line in lines:
            self.lines.setdefault(container_id, []).append((self.clock.now, line))
            self.clock.advance(1.0)

    def restamp(self, container_id: str, ts: float) -> None:
        self.lines[container_id] = [(ts, line) for _, line in self.lines[container_id]]

    async def list(self) -> list[_StubContainer]:
        return [_StubContainer(id=cid) for cid in self.lines]

    async def logs(
        self,
        container_id: str,
        *,
        tail: int | None = 100,
        since: float | None = None,
    ) -> str:
        self.log_calls.append((container_id, tail, since))
        entries = self.lines.get(container_id, [])
        if since is not None:
            entries = [entry for entry in entries if entry[0] >= since]
        if tail is not None:
            entries = entries[-tail:]
        return "".join(f"{line}\n" for _, line in entries)


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
