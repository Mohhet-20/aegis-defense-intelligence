"""Tests for app/geo/distance.py (Phase 7, Section 17 "Spatial queries")."""
from __future__ import annotations

import math

import pytest

from app.geo.distance import EARTH_RADIUS_METERS, bounding_box_for_radius, haversine_km, haversine_meters


def test_same_point_is_zero_distance():
    assert haversine_meters(40.0, -73.0, 40.0, -73.0) == pytest.approx(0.0, abs=1e-6)


def test_known_distance_new_york_to_london():
    # Well-known approximate great-circle distance, ~5570 km.
    ny = (40.7128, -74.0060)
    london = (51.5074, -0.1278)
    km = haversine_km(*ny, *london)
    assert 5500 <= km <= 5600


def test_one_degree_latitude_is_about_111_km_everywhere():
    d1 = haversine_km(0.0, 0.0, 1.0, 0.0)
    d2 = haversine_km(60.0, 0.0, 61.0, 0.0)
    assert 110 <= d1 <= 112
    assert 110 <= d2 <= 112


def test_longitude_distance_shrinks_toward_poles():
    equator_km = haversine_km(0.0, 0.0, 0.0, 1.0)
    near_pole_km = haversine_km(89.0, 0.0, 89.0, 1.0)
    assert near_pole_km < equator_km


def test_antimeridian_crossing_is_short_not_long():
    # 179.9 and -179.9 are 0.2 degrees of longitude apart at the
    # equator, NOT 359.8 -- a naive subtraction would get this wrong.
    close = haversine_km(0.0, 179.9, 0.0, -179.9)
    far = haversine_km(0.0, 0.0, 0.0, 170.0)
    assert close < far
    assert close < 30  # 0.2 deg of longitude at the equator is ~22 km


def test_distance_is_symmetric():
    a, b = (10.0, 20.0), (-5.0, 30.0)
    assert haversine_meters(*a, *b) == pytest.approx(haversine_meters(*b, *a), rel=1e-9)


def test_distance_is_never_negative():
    assert haversine_meters(-90.0, 180.0, 90.0, -180.0) >= 0.0


def test_pole_to_pole_is_half_circumference():
    km = haversine_km(90.0, 0.0, -90.0, 0.0)
    expected = math.pi * EARTH_RADIUS_METERS / 1000.0
    assert km == pytest.approx(expected, rel=1e-6)


def test_bounding_box_contains_center_point():
    min_lat, max_lat, min_lon, max_lon = bounding_box_for_radius(10.0, 20.0, 50.0)
    assert min_lat < 10.0 < max_lat
    assert min_lon < 20.0 < max_lon


def test_bounding_box_actually_bounds_a_point_at_the_radius():
    # A point exactly ~radius_km north of the center must fall inside
    # (or right at the edge of) the computed latitude band.
    center_lat, center_lon, radius_km = 10.0, 20.0, 50.0
    min_lat, max_lat, _, _ = bounding_box_for_radius(center_lat, center_lon, radius_km)
    point_lat = center_lat + (radius_km / 111.32)
    assert min_lat - 1e-6 <= point_lat <= max_lat + 1e-6


def test_bounding_box_near_pole_does_not_crash_and_spans_full_longitude():
    min_lat, max_lat, min_lon, max_lon = bounding_box_for_radius(89.95, 0.0, 100.0)
    assert min_lon == -180.0
    assert max_lon == 180.0
    assert max_lat <= 90.0


def test_bounding_box_clamps_latitude_at_poles():
    min_lat, max_lat, _, _ = bounding_box_for_radius(89.0, 0.0, 500.0)
    assert max_lat == 90.0
    min_lat2, _, _, _ = bounding_box_for_radius(-89.0, 0.0, 500.0)
    assert min_lat2 == -90.0
