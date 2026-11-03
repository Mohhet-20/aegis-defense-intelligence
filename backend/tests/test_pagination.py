"""Bounded pagination: page_size is clamped server-side
regardless of what the client requests, and total reflects a real
COUNT(), not len(items)."""
from __future__ import annotations


def test_page_size_above_the_hard_cap_is_rejected(client, seeded_users, tokens, auth_header):
    """PageParams itself caps page_size at MAX_PAGE_SIZE (200) -- a
    request asking for more is a 422, not silently truncated."""
    response = client.get("/api/v1/assets", params={"page_size": 100000}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 422


def test_page_size_at_the_cap_is_accepted(client, db, org, seeded_users, tokens, auth_header):
    from app.models.asset import Asset

    for i in range(5):
        db.add(Asset(organization_id=org.id, name=f"Asset {i}", entity_type="facility", status="active"))
    db.commit()

    response = client.get("/api/v1/assets", params={"page_size": 200}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 200
    body = response.json()
    assert body["page_size"] == 200
    assert body["total"] == 5


def test_pagination_returns_correct_slice(client, db, org, seeded_users, tokens, auth_header):
    from app.models.asset import Asset

    for i in range(5):
        db.add(Asset(organization_id=org.id, name=f"Asset {i}", entity_type="facility", status="active"))
    db.commit()

    page_one = client.get("/api/v1/assets", params={"page": 1, "page_size": 2}, headers=auth_header(tokens, "viewer"))
    assert len(page_one.json()["items"]) == 2
    assert page_one.json()["total"] == 5

    page_three = client.get("/api/v1/assets", params={"page": 3, "page_size": 2}, headers=auth_header(tokens, "viewer"))
    assert len(page_three.json()["items"]) == 1


def test_invalid_page_size_is_rejected(client, seeded_users, tokens, auth_header):
    response = client.get("/api/v1/assets", params={"page_size": 0}, headers=auth_header(tokens, "viewer"))
    assert response.status_code == 422
