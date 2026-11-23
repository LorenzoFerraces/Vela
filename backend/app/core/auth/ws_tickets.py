"""Short-lived, single-use tickets for WebSocket authentication."""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import WsTicketRecord

_TICKET_TTL = timedelta(seconds=60)


def _make_ticket(user_id: uuid.UUID) -> str:
    # The table stores no user_id column, so the self-describing ticket carries
    # it. The random prefix stays unguessable; the suffix is only trusted after
    # an exact-PK delete proves the row was minted by us.
    return f"{secrets.token_urlsafe(32)}.{user_id.hex}"


def _user_id_from_ticket(ticket: str) -> uuid.UUID | None:
    try:
        _, user_hex = ticket.rsplit(".", 1)
        return uuid.UUID(hex=user_hex)
    except ValueError:
        return None


async def issue_ws_ticket(
    session_factory: async_sessionmaker[AsyncSession],
    user_id: uuid.UUID,
    container_id: str,
    purpose: str,
) -> str:
    ticket = _make_ticket(user_id)
    async with session_factory() as session:
        session.add(
            WsTicketRecord(
                ticket=ticket,
                container_id=container_id,
                purpose=purpose,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()
    return ticket


async def consume_ws_ticket(
    session_factory: async_sessionmaker[AsyncSession],
    ticket: str,
    container_id: str,
    purpose: str,
) -> uuid.UUID | None:
    cutoff = datetime.now(UTC) - _TICKET_TTL
    async with session_factory() as session:
        # Lazy sweep so unused tickets cannot accumulate (as with deploy jobs).
        await session.execute(
            delete(WsTicketRecord).where(WsTicketRecord.created_at < cutoff)
        )
        # Conditional delete is the one-shot guarantee: only one caller can
        # flip a matching row from present to gone.
        matched = cast(
            CursorResult,
            await session.execute(
                delete(WsTicketRecord).where(
                    WsTicketRecord.ticket == ticket,
                    WsTicketRecord.container_id == container_id,
                    WsTicketRecord.purpose == purpose,
                    WsTicketRecord.created_at >= cutoff,
                )
            ),
        )
        consumed = matched.rowcount == 1
        if not consumed:
            # Burn a presented ticket whose scope or TTL is wrong, matching the
            # old ``dict.pop`` behaviour.
            await session.execute(
                delete(WsTicketRecord).where(WsTicketRecord.ticket == ticket)
            )
        await session.commit()
    return _user_id_from_ticket(ticket) if consumed else None


async def reset_for_tests(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory() as session:
        await session.execute(delete(WsTicketRecord))
        await session.commit()
