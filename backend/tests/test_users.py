"""User / organization management: admin-only create,
duplicate rejection, and self-vs-other read scoping."""
from __future__ import annotations


def test_admin_can_create_and_list_users(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/users",
        json={
            "username": "newanalyst",
            "email": "newanalyst@test.example.com",
            "display_name": "New Analyst",
            "password": "AnotherPassword123!",
            "role": "analyst",
        },
        headers=auth_header(tokens, "admin"),
    )
    assert create.status_code == 201
    body = create.json()
    assert body["username"] == "newanalyst"
    assert body["role"] == "analyst"
    assert "password" not in body
    assert "password_hash" not in body

    listing = client.get("/api/v1/users", headers=auth_header(tokens, "viewer"))
    assert listing.status_code == 200
    usernames = {u["username"] for u in listing.json()}
    assert "newanalyst" in usernames


def test_create_user_duplicate_username_is_409(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/users",
        json={
            "username": "admin",
            "email": "different@test.example.com",
            "display_name": "Duplicate",
            "password": "AnotherPassword123!",
        },
        headers=auth_header(tokens, "admin"),
    )
    assert response.status_code == 409


def test_create_user_rejects_invalid_role(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/users",
        json={
            "username": "badrole",
            "email": "badrole@test.example.com",
            "display_name": "Bad Role",
            "password": "AnotherPassword123!",
            "role": "superuser",
        },
        headers=auth_header(tokens, "admin"),
    )
    assert response.status_code == 422


def test_get_and_update_user(client, seeded_users, tokens, auth_header):
    viewer_id = seeded_users["viewer"].id

    get_response = client.get(f"/api/v1/users/{viewer_id}", headers=auth_header(tokens, "admin"))
    assert get_response.status_code == 200
    assert get_response.json()["username"] == "viewer"

    update_response = client.patch(
        f"/api/v1/users/{viewer_id}",
        json={"display_name": "Renamed Viewer", "is_active": False},
        headers=auth_header(tokens, "admin"),
    )
    assert update_response.status_code == 200
    assert update_response.json()["display_name"] == "Renamed Viewer"
    assert update_response.json()["is_active"] is False


def test_get_unknown_user_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/users/not-a-real-id", headers=auth_header(tokens, "admin"))
    assert response.status_code == 404


def test_non_admin_cannot_create_or_update_users(client, seeded_users, tokens, auth_header):
    viewer_id = seeded_users["viewer"].id
    create = client.post(
        "/api/v1/users",
        json={"username": "x", "email": "x@test.example.com", "display_name": "X", "password": "Password123!"},
        headers=auth_header(tokens, "analyst"),
    )
    assert create.status_code == 403

    update = client.patch(
        f"/api/v1/users/{viewer_id}",
        json={"display_name": "Nope"},
        headers=auth_header(tokens, "analyst"),
    )
    assert update.status_code == 403


def test_a_deactivated_user_can_no_longer_authenticate(client, seeded_users, tokens, test_password, auth_header):
    viewer_id = seeded_users["viewer"].id
    client.patch(
        f"/api/v1/users/{viewer_id}",
        json={"is_active": False},
        headers=auth_header(tokens, "admin"),
    )

    response = client.post(
        "/api/v1/auth/login", json={"username_or_email": "viewer", "password": test_password}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Account is disabled"
