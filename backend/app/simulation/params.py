"""Explicit, typed parameter schemas. Validation is strict: unknown keys,
wrong types, non-finite numbers and out-of-range values are all rejected
before anything runs. Parameters are plain data -- nothing here can name code,
a path, a query or a plugin."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class ParamSpec:
    name: str
    type: str  # int | float | bool | choice
    description: str
    default: Any
    unit: str = ""
    min: Optional[float] = None
    max: Optional[float] = None
    choices: Optional[tuple] = None

    def doc(self) -> dict:
        return {"name": self.name, "type": self.type, "description": self.description, "default": self.default,
                "unit": self.unit, "min": self.min, "max": self.max, "choices": list(self.choices) if self.choices else None}


def _check(spec: ParamSpec, v: Any) -> tuple[Any, Optional[str]]:
    t = spec.type
    if t == "bool":
        return (v, None) if isinstance(v, bool) else (None, "must be true or false")
    if t == "choice":
        return (v, None) if (isinstance(v, str) and v in (spec.choices or ())) else (None, f"must be one of {list(spec.choices or [])}")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None, f"must be a number ({t})"
    if isinstance(v, float) and not math.isfinite(v):
        return None, "must be finite"
    if t == "int":
        if isinstance(v, float):
            if not v.is_integer():
                return None, "must be a whole number"
            v = int(v)
    else:
        v = float(v)
    if spec.min is not None and v < spec.min:
        return None, f"must be >= {spec.min:g}"
    if spec.max is not None and v > spec.max:
        return None, f"must be <= {spec.max:g}"
    return v, None


def validate_params(specs: dict[str, ParamSpec], raw: Any) -> tuple[dict, list[dict]]:
    """Returns (clean_params_with_defaults, errors). `errors` is empty iff valid."""
    errors: list[dict] = []
    if not isinstance(raw, dict):
        return {}, [{"param": "*", "message": "parameters must be an object"}]
    if len(raw) > 64:
        return {}, [{"param": "*", "message": "too many parameters"}]
    for k in raw:
        if not isinstance(k, str) or k not in specs:
            errors.append({"param": str(k)[:60], "message": "unknown parameter"})
    clean: dict = {}
    for name, spec in specs.items():
        if name in raw:
            v, err = _check(spec, raw[name])
            if err:
                errors.append({"param": name, "message": err})
            else:
                clean[name] = v
        elif spec.default is not None:
            clean[name] = spec.default
        else:
            errors.append({"param": name, "message": "required"})
    return clean, errors
