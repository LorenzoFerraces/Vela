"""Profile and avatar API tests."""

from __future__ import annotations

import io

from fastapi.testclient import TestClient

from app.core.storage.memory import InMemoryObjectStorage

# Minimal valid PNG (1x1)
PNG_1X1 = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001"
    "0000000108060000001f15c4890000000a494441"
    "54789c6300010000050001010d0a2db400000000"
    "49454e44ae426082"
)


def test_get_me_includes_profile_fields(api_client: TestClient) -> None:
    response = api_client.get("/api/auth/me")
    assert response.status_code == 200
    payload = response.json()
    assert payload["email"] == "user@example.com"
    assert payload["display_name"] is None
    assert payload["pronouns"] is None
    assert payload["avatar_url"] is None


def test_patch_me_updates_display_name_and_pronouns(api_client: TestClient) -> None:
    response = api_client.patch(
        "/api/users/me",
        json={"display_name": "Alex", "pronouns": "they/them"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["display_name"] == "Alex"
    assert payload["pronouns"] == "they/them"

    me = api_client.get("/api/auth/me").json()
    assert me["display_name"] == "Alex"
    assert me["pronouns"] == "they/them"


def test_patch_me_rejects_overlong_display_name(api_client: TestClient) -> None:
    response = api_client.patch(
        "/api/users/me",
        json={"display_name": "x" * 121},
    )
    assert response.status_code == 422


def test_post_avatar_upload_and_delete(
    api_client: TestClient,
    memory_object_storage: InMemoryObjectStorage,
) -> None:
    response = api_client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", io.BytesIO(PNG_1X1), "image/png")},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["avatar_url"] is not None
    assert payload["avatar_url"].startswith("https://storage.test/avatars/")
    assert len(memory_object_storage.object_keys()) == 1

    delete_response = api_client.delete("/api/users/me/avatar")
    assert delete_response.status_code == 200
    assert delete_response.json()["avatar_url"] is None
    assert memory_object_storage.object_keys() == []


def test_post_avatar_rejects_invalid_type(api_client: TestClient) -> None:
    response = api_client.post(
        "/api/users/me/avatar",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )
    assert response.status_code == 400
    assert "JPEG" in response.json()["detail"]


def test_post_avatar_rejects_oversize(api_client: TestClient) -> None:
    oversized = PNG_1X1 + (b"\x00" * (2 * 1024 * 1024))
    response = api_client.post(
        "/api/users/me/avatar",
        files={"file": ("big.png", io.BytesIO(oversized), "image/png")},
    )
    assert response.status_code == 400
    assert "2 MB" in response.json()["detail"]


def test_profile_routes_require_auth(anonymous_client: TestClient) -> None:
    assert anonymous_client.patch("/api/users/me", json={}).status_code == 401
    assert anonymous_client.delete("/api/users/me/avatar").status_code == 401
    assert (
        anonymous_client.post(
            "/api/users/me/avatar",
            files={"file": ("a.png", io.BytesIO(PNG_1X1), "image/png")},
        ).status_code
        == 401
    )


def test_replace_avatar_deletes_previous_object(
    api_client: TestClient,
    memory_object_storage: InMemoryObjectStorage,
) -> None:
    first = api_client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar.png", io.BytesIO(PNG_1X1), "image/png")},
    )
    assert first.status_code == 200
    first_key = memory_object_storage.object_keys()[0]

    second = api_client.post(
        "/api/users/me/avatar",
        files={"file": ("avatar2.png", io.BytesIO(PNG_1X1), "image/png")},
    )
    assert second.status_code == 200
    keys = memory_object_storage.object_keys()
    assert len(keys) == 1
    assert first_key not in keys
