"""Investigation / case management CRUD and status filtering."""
from __future__ import annotations


def test_create_list_and_filter_investigations(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/investigations",
        json={"title": "Loitering near North Gate", "priority": "high"},
        headers=auth_header(tokens, "investigator"),
    )
    assert create.status_code == 201
    body = create.json()
    assert body["status"] == "open"
    assert body["review_status"] == "not_reviewed"

    listing = client.get("/api/v1/investigations", headers=auth_header(tokens, "viewer"))
    assert listing.json()["total"] == 1

    filtered = client.get(
        "/api/v1/investigations", params={"status": "closed"}, headers=auth_header(tokens, "viewer")
    )
    assert filtered.json()["total"] == 0


def test_update_investigation_status_and_resolution(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/investigations",
        json={"title": "Case to close"},
        headers=auth_header(tokens, "investigator"),
    )
    investigation_id = create.json()["id"]

    update = client.patch(
        f"/api/v1/investigations/{investigation_id}",
        json={"status": "closed", "resolution_notes": "Resolved during testing."},
        headers=auth_header(tokens, "investigator"),
    )
    assert update.status_code == 200
    assert update.json()["status"] == "closed"
    assert update.json()["resolution_notes"] == "Resolved during testing."


def test_update_investigation_rejects_invalid_status(client, seeded_users, tokens, auth_header):
    create = client.post(
        "/api/v1/investigations",
        json={"title": "Case with bad update"},
        headers=auth_header(tokens, "investigator"),
    )
    investigation_id = create.json()["id"]

    response = client.patch(
        f"/api/v1/investigations/{investigation_id}",
        json={"status": "not-a-real-status"},
        headers=auth_header(tokens, "investigator"),
    )
    assert response.status_code == 422


def test_viewer_cannot_create_investigation(client, seeded_users, tokens, auth_header):
    response = client.post(
        "/api/v1/investigations",
        json={"title": "Should fail"},
        headers=auth_header(tokens, "viewer"),
    )
    assert response.status_code == 403


def test_get_unknown_investigation_is_404(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/investigations/not-a-real-id", headers=auth_header(tokens, "viewer"))
    assert response.status_code == 404
