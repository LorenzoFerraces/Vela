import uuid

import pytest

from app.core.auth.ws_tickets import consume_ws_ticket, issue_ws_ticket


@pytest.mark.asyncio
async def test_ticket_can_be_consumed_once(db_session_factory) -> None:
    user_id = uuid.uuid4()
    ticket = await issue_ws_ticket(db_session_factory, user_id, "c1", "logs")
    assert await consume_ws_ticket(db_session_factory, ticket, "c1", "logs") == user_id
    assert await consume_ws_ticket(db_session_factory, ticket, "c1", "logs") is None
