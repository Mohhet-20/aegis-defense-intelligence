"""Data source registry CRUD."""
from __future__ import annotations


def test_create_and_get_source(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/sources",
        json={"name": "Perimeter Feed", "source_type": "manual", "description": "Test feed"},
        headers=auth_header(tokens, "analyst"),
    )
    assert create.status_code == 201
    body = create.json()
    assert body["name"] == "Perimeter Feed"
    assert body["status"] == "active"

    get_response = client.get(f"/api/v1/sources/{body['id']}", headers=auth_header(tokens, "viewer"))
    assert get_response.status_code == 200
    assert get_response.json()["id"] == body["id"]


def test_get_unknown_source_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/sources/not-a-real-id", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 404


def test_update_source_status(client, seeded_users, tokens, source, auth_header):
    response = client.patch(
        f"/api/v1/sources/{source.id}",
        json={"status": "inactive"},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "inactive"


def test_update_source_rejects_invalid_status(client, seeded_users, tokens, source, auth_header):
    response = client.patch(
        f"/api/v1/sources/{source.id}",
        json={"status": "not-a-real-status"},
        headers=auth_header(tokens, "analyst"),
    )
    assert response.status_code == 422


def test_list_sources_is_paginated(client, seeded_users, tokens, source, auth_header):
    response = client.get("/api/v1/sources", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == source.id
