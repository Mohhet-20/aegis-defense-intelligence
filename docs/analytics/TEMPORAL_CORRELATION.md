# Temporal Correlation

Phase 3, Section 6 (building on Phase 2 Section 14's
`correlation_service.py`, which this document extends rather than
replaces -- see `docs/analytics/EVENT_CORRELATION.md` for the base
rules, which are unchanged). This document covers exactly what's new
in Phase 3: the per-event-type time-window override.

## The base rule (Phase 2, unchanged)

`temporal_proximity` fires when `abs(a.observed_at - b.observed_at)
<= time_window_seconds` (default 1800s / 30 minutes,
`DEFAULT_TIME_WINDOW_SECONDS` in `correlation_service.py`). This is one
of up to five reasons `_find_reasons()` can produce; a candidate needs
at least `MIN_REASONS_FOR_CANDIDATE = 2` of them, so temporal proximity
alone is never sufficient.

## What's new: per-event-type window override

A single global window is a reasonable default but a poor fit for
every event type -- a fast-moving `intrusion` report and a slow-to-be-
noticed `sensor_offline` report don't belong on the same clock. Section
6 of this phase's spec asks for temporal-window configuration per
signal type; this is implemented as `settings.
FUSION_TIME_WINDOW_SECONDS_BY_TYPE` (`app/core/config.py`, a JSON
object string, default `"{}"`) parsed into
`settings.fusion_time_window_seconds_by_type` (a `dict[str, int]`), and
consumed by a new optional parameter on `correlation_service.recompute()`:

```python
def recompute(
    db, organization_id, *,
    time_window_seconds=DEFAULT_TIME_WINDOW_SECONDS,
    time_window_seconds_by_type: Optional[dict[str, int]] = None,
    ...
):
```

For a given pair `(a, b)`, the window actually used for that pair's
`temporal_proximity` check is:

```python
pair_window = max(
    overrides.get(a.event_type, time_window_seconds),
    overrides.get(b.event_type, time_window_seconds),
)
```

**The larger of the two sides wins.** If either event's type has an
override, that override (or the global default, whichever is larger)
applies to the pair -- an event type not listed in the mapping is
completely unaffected and always uses the global default. This is a
deliberate "be permissive, never silently narrower" choice: an override
exists to WIDEN a window for a type that legitimately needs one, never
to accidentally shrink correlation coverage for types that aren't
listed.

`fusion_service.run_fusion_job()` passes
`settings.fusion_time_window_seconds_by_type` through automatically on
every fusion run (`or None` when the config is the default `{}`, so an
unconfigured deployment behaves byte-for-byte like Phase 2). A direct
call to `POST /correlation/recompute` (unchanged from Phase 2) does
NOT accept this parameter -- the per-type override is specifically a
fusion-run-level configuration point, not exposed as a per-request API
field, since it is meant to be a deployment-wide analytical policy, not
something an individual caller tunes per click.

## The scan-bound correction this required

`recompute()`'s outer loop relies on events being time-sorted and
breaks its inner comparison loop early once a candidate is further away
than the window -- this is what keeps the scan from being O(n^2) over
the whole table. Widening the window for SOME event types means that
early-break bound can no longer just be `time_window_seconds`; it must
be the largest window ANY pair could legitimately need:

```python
max_possible_window = max([time_window_seconds, *overrides.values()]) if overrides else time_window_seconds
```

Without this correction, a longer per-type override would silently
never even be considered for a pair that the (unwidened) early-break
had already skipped past -- exactly the kind of "file exists but isn't
really wired in" gap this project's rules forbid. The fix was written,
then verified with a test that would fail without it (see below).

## Why this was worth actually wiring, not just documenting as a gap

An earlier pass of this phase's work added the settings field and its
parsing property but never connected it to anything -- a real, named
but inert configuration knob. That is exactly the "claimed but not
exercised" trap Section 19 warns about, so before this phase's final
report, the wiring above was written into `correlation_service.py`
(a small, additive change -- Phase 2's existing behavior is
byte-identical when the override map is empty, which Phase 2's own
unmodified `test_correlation.py` suite confirms by still passing in
full) and `fusion_service.py` was updated to pass the setting through.

## Tests

`backend/tests/test_fusion_and_graph.py::
test_per_event_type_time_window_override_is_actually_consumed`:
two events of type `sensor_offline`, different sources, no shared
asset, 3000 seconds apart. With the 1800s global default alone, only
`compatible_event_type` fires (1 reason, below the 2-reason minimum) --
zero correlations. With `{"sensor_offline": 3600}` passed as the
override, `temporal_proximity` also fires (3000 <= 3600) -- one
correlation is created. Phase 2's full `test_correlation.py` suite
(11 tests) passes unchanged, confirming the default-empty-override case
really is behaviorally identical to before this phase.

## What this does NOT do

No per-source, per-organization, or per-pair temporal window --
only per-event-type, and only as a deployment-wide setting (not a
per-API-call parameter on `/correlation/recompute`). No automatic
learning or tuning of window values from historical data -- every
value here is an administrator-set configuration string, same
"human-set, never inferred" discipline as Phase 2's source reliability
weight.
