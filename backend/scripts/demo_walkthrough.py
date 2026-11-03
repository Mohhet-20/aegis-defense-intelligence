"""Load a demonstration of the main AEGIS workflow through the PUBLIC API.

    python scripts/seed.py                                   # accounts + base demo data (dev only)
    python scripts/demo_walkthrough.py --base-url http://127.0.0.1:8000

Every step is an ordinary HTTP call a user could make in the UI, so this is
both demo data and an end-to-end check of the seams between modules:

  1. ingest a JSON file of synthetic events (provenance, duplicate handling)
  2. register evidence, propose a relationship, review it as a human
  3. open an investigation linked to the events, add a note
  4. draft a fusion assessment that cites the evidence
  5. upload a synthetic image and video, run the MOCK detector, review a detection,
     track objects across the video's frames
  6. run the CV model evaluation and a tracking evaluation on synthetic fixtures
  7. register a simulated edge device (no hardware) and activate it
  8. create a scenario from a template, mark it ready and run it (output labelled SIMULATED)
  9. register an MLOps model version and score it on a synthetic labelled set
 10. generate a platform-activity report

All records are synthetic and named "[DEMO] ...". Detector output comes from a
deterministic mock adapter, NOT a trained model: it is not intelligence and says
nothing about real-world accuracy. Running the script twice adds a second set of
records (ingestion de-duplicates the event file itself).

It logs in with an existing account (default: the seeded development `admin`;
password from AEGIS_DEMO_PASSWORD or the documented seed password). It refuses a
non-local --base-url unless --allow-remote is given, so it is not run against a
shared deployment by accident. Exit status 0 = every step succeeded.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import sys
import tempfile
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

DEFAULT_PASSWORD = "DevPassword123!"  # scripts/seed.py development accounts
STEPS: list[tuple[str, bool, str]] = []


class StepFailed(Exception):
    pass


def ok(r: httpx.Response, *codes: int) -> dict:
    if r.status_code not in (codes or (200, 201)):
        raise StepFailed(f"{r.request.method} {r.request.url.path} -> {r.status_code}: {r.text[:300]}")
    return r.json() if r.content else {}


def step(name: str):
    def wrap(fn):
        def run(*a, **kw):
            try:
                detail = fn(*a, **kw) or ""
                STEPS.append((name, True, detail))
                print(f"PASS {name}" + (f"  ({detail})" if detail else ""))
            except StepFailed as exc:
                STEPS.append((name, False, str(exc)))
                print(f"FAIL {name}  [{exc}]")
        return run
    return wrap


def synthetic_png(w: int = 160, h: int = 120) -> bytes:
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), (40, 48, 60))
    ImageDraw.Draw(img).rectangle([50, 30, 110, 100], fill=(200, 200, 210))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def synthetic_mp4(frames: int = 24, w: int = 160, h: int = 120, fps: int = 4) -> bytes:
    import cv2
    import numpy as np

    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "demo.mp4")
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (w, h))
        for i in range(frames):
            frame = np.full((h, w, 3), 50, dtype=np.uint8)
            x = 10 + i * 4  # one bright block moving left to right
            frame[40:90, x:x + 30] = 220
            writer.write(frame)
        writer.release()
        return Path(path).read_bytes()


class Demo:
    def __init__(self, client: httpx.Client):
        self.c = client
        self.tag = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        self.event_ids: list[str] = []
        self.evidence_id: str | None = None
        self.video_job_id: str | None = None

    def mock_model_id(self) -> str:
        models = ok(self.c.get("/cv/models"))["items"]
        mock = [m for m in models if m["adapter_key"] == "mock_detector_v1"]
        if not mock:
            raise StepFailed("no mock_detector_v1 model registered (run scripts/seed.py first)")
        return mock[0]["id"]

    @step("ingest synthetic events from a JSON file")
    def ingest(self):
        src = ok(self.c.post("/sources", json={"name": f"[DEMO] Perimeter log {self.tag}", "source_type": "manual",
                                                "description": "Synthetic demonstration source"}), 201)
        base = datetime.now(timezone.utc) - timedelta(hours=3)
        records = [{"event_type": "perimeter_motion", "title": f"[DEMO] Motion at gate {g}", "severity": sev,
                    "observed_at": (base + timedelta(minutes=12 * i)).isoformat(), "external_id": f"demo-{self.tag}-{i}",
                    "latitude": 38.89 + i * 0.002, "longitude": -77.03 - i * 0.002}
                   for i, (g, sev) in enumerate([("A", "low"), ("B", "medium"), ("B", "high"), ("C", "medium")])]
        records.append(dict(records[0]))  # an exact duplicate, to show de-duplication
        body = json.dumps(records).encode()
        job = ok(self.c.post("/ingestion/jobs", data={"source_id": src["id"]},
                             files={"file": ("demo_events.json", body, "application/json")}), 201)
        events = ok(self.c.get("/events", params={"source_id": src["id"], "page_size": 50}))["items"]
        self.event_ids = [e["id"] for e in events]
        if len(self.event_ids) < 2:
            raise StepFailed(f"expected >= 2 events, got {len(self.event_ids)}")
        return f"accepted={job['accepted_count']} duplicates={job['duplicate_count']}"

    @step("register evidence and review a proposed relationship")
    def evidence(self):
        ev = ok(self.c.post("/evidence", json={"evidence_type": "observation", "title": "[DEMO] Gate B motion log",
                                               "event_id": self.event_ids[1]}), 201)
        self.evidence_id = ev["id"]
        rel = ok(self.c.post("/relationships", json={
            "source_ref_type": "event", "source_ref_id": self.event_ids[1], "target_ref_type": "event",
            "target_ref_id": self.event_ids[2], "relationship_type": "temporally_associated",
            "explanation": "Same gate, 12 minutes apart (synthetic)"}), 201)
        ok(self.c.post(f"/relationships/{rel['id']}/review", json={"review_status": "confirmed",
                                                                    "review_note": "Analyst confirmed (demo)"}))
        return "relationship confirmed by a human reviewer"

    @step("open an investigation with a note")
    def investigation(self):
        inv = ok(self.c.post("/investigations", json={
            "title": f"[DEMO] Repeated gate B activity {self.tag}", "description": "Synthetic demonstration case",
            "priority": "normal", "purpose": "demonstration", "scope": "synthetic events only",
            "linked_event_ids": self.event_ids[:3]}), 201)
        ok(self.c.post(f"/investigations/{inv['id']}/notes", json={
            "body": "Two motion events at gate B within 12 minutes. No conclusion drawn; more data needed.",
            "note_kind": "observed_fact"}), 201)
        return inv["id"]

    @step("draft an assessment citing evidence")
    def assessment(self):
        a = ok(self.c.post("/assessments", json={
            "title": f"[DEMO] Gate B activity assessment {self.tag}", "question": "Is gate B activity unusual?",
            "summary": "Synthetic draft for demonstration.", "assumptions": ["Sensor clocks are synchronised"],
            "information_gaps": ["No camera coverage of gate B"], "confidence_level": "low",
            "confidence_rationale": "Two synthetic events only"}), 201)
        ok(self.c.post(f"/assessments/{a['id']}/evidence", json={"evidence_id": self.evidence_id, "role": "supporting"}), 200, 201)
        return a["id"]

    @step("run the mock detector on an image and review a detection")
    def image_detection(self):
        media = ok(self.c.post("/media", files={"file": ("demo_scene.png", synthetic_png(), "image/png")}), 201)
        job = ok(self.c.post("/inference/jobs", json={"media_asset_id": media["id"], "model_record_id": self.mock_model_id(),
                                                      "job_type": "image_detection"}), 201)
        dets = ok(self.c.get(f"/inference/jobs/{job['id']}/detections"))["items"]
        if not dets:
            return "job completed with 0 detections"
        ok(self.c.post(f"/detections/{dets[0]['id']}/review", json={"review_status": "confirmed",
                                                                      "review_note": "Demo review of MOCK output"}))
        return f"{len(dets)} mock detection(s), first one reviewed"

    @step("analyse a synthetic video and track objects across frames")
    def video_tracking(self):
        media = ok(self.c.post("/media", files={"file": ("demo_clip.mp4", synthetic_mp4(), "video/mp4")}), 201)
        job = ok(self.c.post("/inference/jobs", json={"media_asset_id": media["id"], "model_record_id": self.mock_model_id(),
                                                      "job_type": "video_frame_analysis", "frame_sample_interval_seconds": 0.5}), 201)
        self.video_job_id = job["id"]
        tj = ok(self.c.post("/tracking/jobs", json={"inference_job_id": job["id"]}), 201)
        return f"tracking job {tj.get('status')}"

    @step("run CV and tracking evaluations on synthetic fixtures")
    def evaluations(self):
        ev = ok(self.c.post("/evaluation/runs", json={"model_record_id": self.mock_model_id(), "sample_count": 20}), 201)
        tr = ok(self.c.post("/tracking/evaluation/runs", json={}), 201)
        return f"mock detector on synthetic fixture: precision={ev.get('precision')} recall={ev.get('recall')}; tracking run {tr.get('id', '')[:8]}"

    @step("register and activate a simulated edge device")
    def device(self):
        d = ok(self.c.post("/devices", json={"device_identifier": f"demo-edge-{self.tag}", "device_name": "[DEMO] Simulated gate node",
                                             "device_type": "edge_gateway", "metadata_note": "Simulated; no hardware"}), 201)
        dev = d.get("device", d)
        ok(self.c.post(f"/devices/{dev['id']}/activate", json={"reason": "demo"}))
        return "registered + activated (API key shown once in the response, discarded here)"

    @step("create, ready and run a scenario (SIMULATED)")
    def scenario(self):
        tpl = next(t for t in ok(self.c.get("/simulation/templates"))["templates"] if t["id"] == "threshold_sensitivity")
        sc = ok(self.c.post("/scenarios", json={"title": f"[DEMO] {tpl['title']} {self.tag}", "question": tpl["question"],
                                                "template_id": tpl["id"], "simulator_id": tpl["simulator_id"],
                                                "params": tpl["params"], "assumptions": tpl["assumptions"], "seed": 7}), 201)
        ready = ok(self.c.post(f"/scenarios/{sc['id']}/ready"))
        run = ok(self.c.post(f"/scenarios/{ready['id']}/runs", json={"seed": 7}), 201)
        return f"run {run.get('status')}"

    @step("register a model version and score it on a synthetic labelled set")
    def mlops(self):
        m = ok(self.c.post("/mlops/models", json={"name": f"demo-classifier-{self.tag}", "version": "1.0.0",
                                                  "task_type": "classification", "release_notes": "Synthetic demo"}), 201)
        # 40 synthetic samples, every 7th one predicted wrongly.
        samples = [{"sample_ref": f"s{i}", "true_label": "pos" if i % 2 else "neg",
                    "predicted_label": ("pos" if i % 2 else "neg") if i % 7 else ("neg" if i % 2 else "pos")}
                   for i in range(40)]
        run = ok(self.c.post("/mlops/experiments", json={
            "model_record_id": m["id"], "experiment_name": "demo baseline", "idempotency_key": f"demo-{self.tag}",
            "classification": {"dataset_name": "synthetic-demo", "dataset_version": "1", "is_synthetic": True,
                               "positive_label": "pos", "samples": samples}}), 201)
        return f"experiment {run.get('status')}"

    @step("generate a platform-activity report")
    def report(self):
        now = datetime.now(timezone.utc)
        rep = ok(self.c.post("/reporting/reports", json={"template_key": "platform_activity", "format": "html",
                                                         "start": (now - timedelta(days=7)).isoformat(), "end": now.isoformat()}), 201)
        return f"report {rep.get('status')}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8000")
    ap.add_argument("--username", default="admin")
    ap.add_argument("--allow-remote", action="store_true")
    args = ap.parse_args()
    if urlparse(args.base_url).hostname not in ("127.0.0.1", "localhost", "::1") and not args.allow_remote:
        print("Refusing: --base-url is not local. This script adds demo records; pass --allow-remote if you mean it.")
        return 2
    client = httpx.Client(base_url=args.base_url.rstrip("/") + "/api/v1", timeout=120)
    login = client.post("/auth/login", json={"username_or_email": args.username,
                                             "password": os.environ.get("AEGIS_DEMO_PASSWORD", DEFAULT_PASSWORD)})
    if login.status_code != 200:
        print(f"Login failed ({login.status_code}). Seed a development database first: python scripts/seed.py")
        return 1
    client.headers["Authorization"] = f"Bearer {login.json()['access_token']}"
    demo = Demo(client)
    started = time.monotonic()
    for fn in (demo.ingest, demo.evidence, demo.investigation, demo.assessment, demo.image_detection,
               demo.video_tracking, demo.evaluations, demo.device, demo.scenario, demo.mlops, demo.report):
        fn()
    passed = sum(1 for _, good, _ in STEPS if good)
    print(f"\n{passed}/{len(STEPS)} steps succeeded in {time.monotonic() - started:.1f}s. "
          "All records are synthetic ([DEMO]); detections come from a mock adapter.")
    return 0 if passed == len(STEPS) else 1


if __name__ == "__main__":
    sys.exit(main())
