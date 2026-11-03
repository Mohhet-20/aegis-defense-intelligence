"""Unit tests for app/sensors/units.py -- the
closed, documented unit-conversion table. Pure functions, no DB."""
from __future__ import annotations

import pytest

from app.sensors import units as unit_lib


def test_identity_conversion_same_unit():
    result = unit_lib.convert_unit(22.0, "celsius", "celsius")
    assert result.converted_value == 22.0
    assert result.original_unit == result.converted_unit == "celsius"


def test_temperature_celsius_to_fahrenheit():
    result = unit_lib.convert_unit(0.0, "celsius", "fahrenheit")
    assert result.converted_value == 32.0
    result = unit_lib.convert_unit(100.0, "celsius", "fahrenheit")
    assert result.converted_value == 212.0


def test_temperature_celsius_to_kelvin():
    result = unit_lib.convert_unit(0.0, "celsius", "kelvin")
    assert result.converted_value == 273.15


def test_length_kilometers_to_meters():
    result = unit_lib.convert_unit(1.0, "kilometers", "meters")
    assert result.converted_value == 1000.0


def test_length_miles_to_feet_round_trip():
    result = unit_lib.convert_unit(1.0, "miles", "feet")
    # 1 mile = 5280 feet, within the module's own documented rounding.
    assert abs(result.converted_value - 5280.0) < 0.5


def test_speed_kph_to_mps():
    result = unit_lib.convert_unit(36.0, "kilometers_per_hour", "meters_per_second")
    assert abs(result.converted_value - 10.0) < 1e-6


def test_incompatible_dimension_raises():
    with pytest.raises(unit_lib.IncompatibleUnitError):
        unit_lib.convert_unit(22.0, "celsius", "meters")


def test_unrecognized_unit_raises():
    with pytest.raises(unit_lib.IncompatibleUnitError):
        unit_lib.convert_unit(22.0, "celsius", "not_a_real_unit")
    with pytest.raises(unit_lib.IncompatibleUnitError):
        unit_lib.convert_unit(22.0, "not_a_real_unit", "celsius")


def test_units_compatible_true_for_same_dimension():
    assert unit_lib.units_compatible("celsius", "fahrenheit") is True
    assert unit_lib.units_compatible("meters", "feet") is True


def test_units_compatible_false_for_different_dimension():
    assert unit_lib.units_compatible("celsius", "meters") is False


def test_units_compatible_false_for_unknown_unit_never_raises():
    assert unit_lib.units_compatible("celsius", "bogus") is False
    assert unit_lib.units_compatible("bogus", "also_bogus") is False


def test_no_calibration_coefficient_applied_never_present_in_result():
    result = unit_lib.convert_unit(22.0, "celsius", "fahrenheit")
    # ConversionResult has no calibration field at all -- the module
    # documents that it never invents one; this just locks the shape.
    assert not hasattr(result, "calibration_offset")
    assert not hasattr(result, "calibration_coefficient")


def test_supported_units_and_dimensions_are_nonempty_and_closed():
    assert "celsius" in unit_lib.SUPPORTED_UNITS
    assert "temperature" in unit_lib.SUPPORTED_DIMENSIONS
    assert unit_lib.unit_dimension("celsius") == "temperature"
    assert unit_lib.unit_dimension("totally_unknown") is None
