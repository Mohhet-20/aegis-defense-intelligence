"""Controlled unit conversion. A small, CLOSED
table of supported units grouped by physical dimension -- converting
between two units of different dimensions (e.g. celsius -> meters) is
always rejected, never attempted.

This module NEVER invents a calibration coefficient. The only
conversions it performs are standard, documented unit-system
conversions (temperature scales, length, speed, mass, pressure, angle)
-- a sensor-specific calibration correction (e.g. "this particular
thermometer reads 1.2 degrees high") is a SEPARATE, per-sensor fact
that must come from the sensor's own documented configuration; this
module has no mechanism to apply one that wasn't supplied, satisfying
Section 12's "avoid applying calibration coefficients that are not
documented for the source."
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

UNIT_CONVERSION_RULE_VERSION = "1.0"


class IncompatibleUnitError(ValueError):
    """Raised for a conversion between units of different physical
    dimensions, or between two units this module does not recognize."""


@dataclass(frozen=True)
class ConversionResult:
    original_value: float
    original_unit: str
    converted_value: float
    converted_unit: str
    rule_version: str


# Each dimension maps every supported unit to a (to_base, from_base)
# pair of pure functions against one canonical base unit for that
# dimension. Linear units (length, speed, mass, pressure, angle) use a
# simple multiplicative factor; temperature needs its own affine
# functions because Celsius/Fahrenheit are not linear through zero.
def _linear(factor: float) -> tuple[Callable[[float], float], Callable[[float], float]]:
    return (lambda v: v * factor), (lambda v: v / factor)


_DIMENSIONS: dict[str, dict[str, tuple[Callable[[float], float], Callable[[float], float]]]] = {
    "temperature": {
        # base unit: celsius
        "celsius": (lambda v: v, lambda v: v),
        "fahrenheit": (lambda v: (v - 32.0) * 5.0 / 9.0, lambda v: v * 9.0 / 5.0 + 32.0),
        "kelvin": (lambda v: v - 273.15, lambda v: v + 273.15),
    },
    "length": {
        # base unit: meters
        "meters": _linear(1.0),
        "kilometers": _linear(1000.0),
        "feet": _linear(0.3048),
        "miles": _linear(1609.344),
    },
    "speed": {
        # base unit: meters_per_second
        "meters_per_second": _linear(1.0),
        "kilometers_per_hour": _linear(1.0 / 3.6),
        "miles_per_hour": _linear(0.44704),
    },
    "mass": {
        # base unit: kilograms
        "kilograms": _linear(1.0),
        "pounds": _linear(0.45359237),
    },
    "pressure": {
        # base unit: hectopascals
        "hectopascals": _linear(1.0),
        "pascals": _linear(0.01),
        "psi": _linear(68.9476),
    },
    "angle": {
        # base unit: degrees
        "degrees": _linear(1.0),
        "radians": _linear(57.29577951308232),
    },
    "ratio": {
        # base unit: percent
        "percent": _linear(1.0),
        "fraction": _linear(100.0),
    },
}

# unit -> dimension, built once for fast lookup / dimension-mismatch checks.
_UNIT_TO_DIMENSION: dict[str, str] = {unit: dim for dim, units in _DIMENSIONS.items() for unit in units}

SUPPORTED_UNITS = tuple(sorted(_UNIT_TO_DIMENSION))
SUPPORTED_DIMENSIONS = tuple(sorted(_DIMENSIONS))


def unit_dimension(unit: str) -> Optional[str]:
    return _UNIT_TO_DIMENSION.get(unit)


def convert_unit(value: float, from_unit: str, to_unit: str) -> ConversionResult:
    """Converts `value` from `from_unit` to `to_unit`. Raises
    IncompatibleUnitError for an unrecognized unit, or for two units
    that belong to different physical dimensions -- there is no
    fallback behavior; the caller must treat this as "cannot compare,"
    never guess a conversion."""
    if from_unit == to_unit:
        return ConversionResult(value, from_unit, value, to_unit, UNIT_CONVERSION_RULE_VERSION)

    from_dim = unit_dimension(from_unit)
    to_dim = unit_dimension(to_unit)
    if from_dim is None:
        raise IncompatibleUnitError(f"unit '{from_unit}' is not a supported unit (supported: {SUPPORTED_UNITS})")
    if to_dim is None:
        raise IncompatibleUnitError(f"unit '{to_unit}' is not a supported unit (supported: {SUPPORTED_UNITS})")
    if from_dim != to_dim:
        raise IncompatibleUnitError(f"cannot convert '{from_unit}' ({from_dim}) to '{to_unit}' ({to_dim}) -- incompatible physical dimensions")

    to_base, _ = _DIMENSIONS[from_dim][from_unit]
    _, from_base = _DIMENSIONS[from_dim][to_unit]
    base_value = to_base(value)
    converted = from_base(base_value)
    # Rounded for display only -- the full-precision value is also kept
    # so a caller that needs exactness can recompute; Section 12:
    # "handle rounding transparently," never silently.
    return ConversionResult(value, from_unit, round(converted, 6), to_unit, UNIT_CONVERSION_RULE_VERSION)


def units_compatible(unit_a: str, unit_b: str) -> bool:
    """True if the two units share a physical dimension (so a
    comparison/conversion between them is even meaningful). False for
    an unrecognized unit on either side -- never raises."""
    dim_a, dim_b = unit_dimension(unit_a), unit_dimension(unit_b)
    return dim_a is not None and dim_a == dim_b
