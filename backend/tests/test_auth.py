"""Authentication: login, refresh, /me, and account lockout."""
from __future__ import annotations


def test_login_success_returns_tokens(client, seeded_users, test_password):
    response = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": test_password},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["access_token"]
    assert body["refresh_token"]


def test_login_wrong_password_rejected_generically(client, seeded_users):
    response = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": "wrong-password"},
    )
    assert response.status_code == 401
    # Never reveals whether the username or the password was wrong.
    assert response.json()["detail"] == "Invalid credentials"


def test_login_unknown_user_rejected_with_same_message(client, seeded_users):
    response = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "nobody", "password": "whatever123"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid credentials"


def test_account_locks_out_after_repeated_failures(client, seeded_users, test_password):
    for _ in range(5):
        response = client.post(
            "/api/v1/auth/login",
            json={"username_or_email": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 401

    # The 6th attempt, even with the CORRECT password, is now locked out.
    response = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "admin", "password": test_password},
    )
    assert response.status_code == 401
    assert "locked" in response.json()["detail"].lower()


def test_refresh_token_issues_new_access_token(client, seeded_users, test_password):
    login = client.post(
        "/api/v1/auth/login",
        json={"username_or_email": "analyst", "password": test_password},
    )
    refresh_token = login.json()["refresh_token"]

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_refresh_rejects_an_access_token_used_as_refresh(client, seeded_users, tokens):
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": tokens["analyst"]})
    assert response.status_code == 401
    assert response.json()["detail"] == "Expected a refresh token"


def test_me_returns_current_user(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/auth/me", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    body = response.json()
    assert body["username"] == "viewer"
    assert body["role"] == "viewer"


def test_protected_route_without_token_is_401(client, seeded_users):
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_protected_route_with_garbage_token_is_401(client, seeded_users):
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert response.status_code == 401
