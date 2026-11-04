---
title: AEGIS
emoji: 🛰️
colorFrom: blue
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
license: mit
short_description: Analyst platform demo -- real detector, synthetic data
---

# AEGIS -- public demo

A full-stack analyst platform (FastAPI + React): ingest multi-source data, run and review a real
pretrained object detector (SSD-MobileNet, evaluated on COCO photos), build investigations from
evidence, and report on it.

**Sign in with one click** as administrator, analyst, investigator or viewer. All data is
**synthetic** and resets every 6 hours; visitors enter through *Explore the live demo* (a guest analyst session, no password).
Decision-support demonstration only: no targeting, weapon-control or automated-action capability.

Source code, documentation and tests: __GITHUB_URL__

Built from the repository's root `Dockerfile` (exported with `scripts/export_hf_space.py`).
