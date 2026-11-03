# License decision

**Decision (2026-10-19, owner): MIT.** `LICENSE` at the repository root carries the standard MIT text,
`Copyright (c) 2026 balak`; `frontend/package.json` declares `"license": "MIT"`.

## Third-party components and their licences

| Component | Licence | How it is used | Obligation |
|---|---|---|---|
| Backend Python dependencies (FastAPI, SQLAlchemy, Pydantic, NumPy, SciPy, OpenCV, ...) | MIT, BSD-3-Clause, Apache-2.0, MIT-CMU, Unlicense | installed from `requirements.txt` | keep their notices when redistributing them |
| `psycopg2-binary` | LGPL with exceptions | installed, used unmodified as a library | obligations arise only if psycopg2 itself is modified and redistributed |
| Frontend runtime (React, React Router, Leaflet, ...) | MIT (7 packages), BSD-2-Clause (`leaflet`) | bundled into `dist/` | keep notices in distributed builds (licence comments / a notices file) |
| SSD-MobileNet v1 COCO weights | Apache-2.0 (TensorFlow Object Detection API model zoo) | downloaded on demand by `scripts/fetch_models.py`, never committed | attribution; ship `PROVENANCE.json` if you redistribute the weights |
| OpenCV graph config `ssd_mobilenet_v1_coco_2017_11_17.pbtxt` | Apache-2.0 (opencv_extra) | downloaded on demand | as above |
| COCO 2017 annotations / images | CC BY 4.0 / per-image Flickr licences (recorded per image in the manifest) | downloaded for evaluation, never committed to git; the public-demo container image (root `Dockerfile`) bundles the 200-image sample with its manifest and displays three CC BY photos | every COCO image is Creative Commons or public domain; keep `manifest.json` (licence + Flickr URL per image) with the images and credit displayed photos; build with `FETCH_EVAL_DATA=0` to leave the sample out |

## History

Until 1.0.0-rc.2 the map used `react-leaflet`, licensed under the Hippocratic License 2.1 (not
OSI-approved; human-rights-use conditions, indemnity, notice requirement). At the owner's request it was
replaced by a small wrapper over plain Leaflet (`frontend/src/components/geo/LeafletMap.tsx`), so the
shipped frontend contains only MIT and BSD-2 code. The MIT vs Apache-2.0 comparison that informed the
choice: MIT is shorter and simpler; Apache-2.0 adds an express patent grant and NOTICE handling.
