"""Integration tests for saved images and Dockerfile template CRUD."""

from __future__ import annotations

import uuid

from fastapi.testclient import TestClient


def test_saved_images_crud(api_client: TestClient) -> None:
    create = api_client.post(
        "/api/saved-images/",
        json={"ref": "nginx:alpine"},
    )
    assert create.status_code == 201
    created = create.json()
    image_id = created["id"]
    assert created["ref"] == "nginx:alpine"

    listed = api_client.get("/api/saved-images/")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    fetched = api_client.get(f"/api/saved-images/{image_id}")
    assert fetched.status_code == 200

    updated = api_client.patch(
        f"/api/saved-images/{image_id}",
        json={"ref": "nginx:latest"},
    )
    assert updated.status_code == 200
    assert updated.json()["ref"] == "nginx:latest"

    deleted = api_client.delete(f"/api/saved-images/{image_id}")
    assert deleted.status_code == 204

    missing = api_client.get(f"/api/saved-images/{image_id}")
    assert missing.status_code == 404


def test_saved_images_duplicate_ref(api_client: TestClient) -> None:
    api_client.post("/api/saved-images/", json={"ref": "redis:7"})
    second = api_client.post("/api/saved-images/", json={"ref": "redis:7"})
    assert second.status_code == 409


def test_saved_images_requires_auth(anonymous_client: TestClient) -> None:
    response = anonymous_client.get("/api/saved-images/")
    assert response.status_code == 401


def test_saved_images_other_user_isolated(
    api_client: TestClient, other_user_client: TestClient
) -> None:
    create = api_client.post(
        "/api/saved-images/",
        json={"ref": "private:mine"},
    )
    image_id = create.json()["id"]

    assert other_user_client.get("/api/saved-images/").json() == []
    assert other_user_client.get(f"/api/saved-images/{image_id}").status_code == 404
    assert (
        other_user_client.delete(f"/api/saved-images/{image_id}").status_code == 404
    )


def test_dockerfile_templates_crud(api_client: TestClient) -> None:
    create = api_client.post(
        "/api/dockerfiles/",
        json={
            "name": "web-app",
            "contents": "FROM node:20-alpine\nWORKDIR /app\n",
        },
    )
    assert create.status_code == 201
    created = create.json()
    template_id = created["id"]
    assert created["name"] == "web-app"

    listed = api_client.get("/api/dockerfiles/")
    assert listed.status_code == 200
    assert len(listed.json()) == 1

    patch_contents = api_client.patch(
        f"/api/dockerfiles/{template_id}",
        json={"contents": "FROM node:22-alpine\n"},
    )
    assert patch_contents.status_code == 200
    assert "node:22" in patch_contents.json()["contents"]
    assert patch_contents.json()["name"] == "web-app"

    patch_name = api_client.patch(
        f"/api/dockerfiles/{template_id}",
        json={"name": "web-app-v2"},
    )
    assert patch_name.status_code == 200
    assert patch_name.json()["name"] == "web-app-v2"

    deleted = api_client.delete(f"/api/dockerfiles/{template_id}")
    assert deleted.status_code == 204


def test_dockerfile_templates_duplicate_name(api_client: TestClient) -> None:
    api_client.post(
        "/api/dockerfiles/",
        json={"name": "api", "contents": "FROM python:3.12\n"},
    )
    second = api_client.post(
        "/api/dockerfiles/",
        json={"name": "api", "contents": "FROM python:3.11\n"},
    )
    assert second.status_code == 409


def test_dockerfile_patch_requires_field(api_client: TestClient) -> None:
    create = api_client.post(
        "/api/dockerfiles/",
        json={"name": "empty-patch", "contents": "FROM alpine\n"},
    )
    template_id = create.json()["id"]
    response = api_client.patch(f"/api/dockerfiles/{template_id}", json={})
    assert response.status_code == 400


def test_dockerfile_templates_other_user_isolated(
    api_client: TestClient, other_user_client: TestClient
) -> None:
    create = api_client.post(
        "/api/dockerfiles/",
        json={"name": "secret", "contents": "FROM scratch\n"},
    )
    template_id = create.json()["id"]

    assert other_user_client.get("/api/dockerfiles/").json() == []
    assert (
        other_user_client.get(f"/api/dockerfiles/{template_id}").status_code == 404
    )


def test_dockerfile_not_found(api_client: TestClient) -> None:
    missing_id = str(uuid.uuid4())
    assert api_client.get(f"/api/dockerfiles/{missing_id}").status_code == 404
