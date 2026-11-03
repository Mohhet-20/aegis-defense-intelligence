# Edge and Offline Sync Contracts — Planned (Phase 8–9)

**Status: PLANNED. No edge agent, offline buffer, or sync protocol
exists yet.** The `Device` model ships in Phase 1 as a registry shape
only — nothing populates it from a real device.

## What Phase 1 actually ships

- `Device`: id, device name, device type, software version, reported
  health (free-form status string), `last_seen_at`, configuration
  version, synchronization status. No API routes expose `Device` yet
  (it's a schema placeholder, not a registered module in Section 6's
  12 — Phase 9 is where it gets real endpoints and a real service).

## What Phase 8 (Edge AI and Offline Operation) will add

- **Local event buffering** on a device that's lost connectivity, with
  a real local identifier scheme that survives the eventual sync.
- **Synchronization cursors** so a device and the central server agree
  on "everything up to here is synced."
- **Idempotent uploads** — re-sending a batch after a dropped connection
  must not create duplicate events; the dedup logic in the Phase 1
  ingestion pipeline (`source_id` + `external_id`) is the pattern this
  will extend, not replace.
- **Retry policy and conflict handling** for a device that comes back
  online with data that overlaps or contradicts what the server already
  has.
- **Online/offline status and version compatibility** reporting, so a
  device running an old protocol version is handled explicitly, not
  silently.

## What Phase 9 (Fleet Management and Device Observability) will add

- Real `Device` API routes: inventory list, health telemetry ingestion,
  software/model version reporting, authorized configuration push.
- **Device authorization** — a device must be explicitly registered and
  credentialed before it can sync anything; Phase 1 defines no device
  credential type yet.
- **Synchronization audit records** — every sync event, success or
  conflict, recorded in a form reviewable by an administrator.

## Binding principles (apply from Phase 8–9 onward)

- Do not claim offline synchronization "works" until it has actually
  been implemented AND tested with a real simulated disconnect/
  reconnect cycle — Section 14 and Rule 5 are explicit about this.
- A sync conflict (device and server both changed overlapping data
  while disconnected) must be surfaced and resolved by an explicit,
  documented policy — never silently resolved by "last write wins"
  without that being a stated decision.
- A device reporting a software/model version the server doesn't
  recognize must be flagged, not assumed compatible.

## What Phase 1 does NOT do

No device can register, authenticate, or sync anything. The `Device`
table exists with zero rows and no API surface.
