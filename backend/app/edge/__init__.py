"""The simulated edge runtime.

Everything under this package models code that would, in a real
deployment, run ON the physical edge device -- not inside this backend
process. It is wired up here, and tested here, purely IN-PROCESS:
`local_store.LocalEdgeStore` is a genuinely separate SQLite database
file (never the central app's SQLAlchemy session/engine -- "local vs.
central ownership" is a real architectural boundary, not a fiction),
and `simulator.SimulatedEdgeNode` talks to the real FastAPI application
over real HTTP (via `httpx`), exactly as a physical device would,
rather than calling service functions directly.

Honestly stated (see docs/architecture/EDGE_ARCHITECTURE.md Section 18
and the final report): this edge runtime has been exercised in
SIMULATION ONLY. No physical edge hardware is available in this
environment, so nothing here has been run on real device hardware.
"""
