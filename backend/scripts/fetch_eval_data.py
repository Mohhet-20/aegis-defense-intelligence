"""Build the real-image evaluation set: a deterministic sample of COCO val2017.

    python scripts/fetch_eval_data.py                         # 200 images, seed 0
    python scripts/fetch_eval_data.py --count 500 --seed 1
    python scripts/fetch_eval_data.py --annotations-zip D:\\dl\\annotations_trainval2017.zip   # offline annotations

Writes CV_EVAL_DATA_DIR/coco_val2017_subset/ (default backend/eval_data/...):
  images/<id>.jpg   the sampled images, each SHA-256 recorded
  manifest.json     dataset name/version, per-image licence, and ground-truth boxes
                    for the platform's classes (COCO person -> person, COCO
                    vehicle classes -> vehicle); crowd regions are kept as "ignore"
                    boxes, as in the COCO protocol.

Images are sampled uniformly from ALL val2017 images (not only ones containing
people or vehicles), so precision is measured against realistic distractors.
COCO annotations are CC BY 4.0; each image keeps its own Flickr licence, recorded
per image. Nothing here is committed to git.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import random
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402
import numpy as np  # noqa: E402

from app.core.config import get_settings  # noqa: E402

ANNOTATIONS_URL = "http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
ANNOTATIONS_SHA256 = "113a836d90195ee1f884e704da6304dfaaecff1f023f49b6ca93c4aaae470268"  # pragma: allowlist secret (public SHA-256 pin)
MEMBER = "annotations/instances_val2017.json"
PERSON = {1}
VEHICLES = {2, 3, 4, 5, 6, 7, 8, 9}  # bicycle, car, motorcycle, airplane, bus, train, truck, boat
DATASET_NAME = "coco_val2017_subset"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _load_annotations(zip_path: Path | None) -> dict:
    if zip_path is None:
        print(f"downloading {ANNOTATIONS_URL} (~253 MB)")
        data = httpx.get(ANNOTATIONS_URL, follow_redirects=True, timeout=600).content
    else:
        data = zip_path.read_bytes()
    if _sha256(data) != ANNOTATIONS_SHA256:
        raise SystemExit("annotations archive SHA-256 mismatch -- refusing to use it")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return json.loads(zf.read(MEMBER))


def _label(category_id: int) -> str | None:
    return "person" if category_id in PERSON else "vehicle" if category_id in VEHICLES else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--count", type=int, default=200)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--annotations-zip", type=Path, default=None)
    args = ap.parse_args()
    if not 1 <= args.count <= 5000:
        raise SystemExit("--count must be between 1 and 5000")

    import cv2  # local import: only needed to check that each image decodes

    ann = _load_annotations(args.annotations_zip)
    licences = {lic["id"]: {"name": lic["name"], "url": lic["url"]} for lic in ann["licenses"]}
    images = sorted(ann["images"], key=lambda im: im["id"])
    chosen = random.Random(args.seed).sample(images, args.count)
    by_image: dict[int, list] = {}
    for a in ann["annotations"]:
        label = _label(a["category_id"])
        if label is not None:
            by_image.setdefault(a["image_id"], []).append(a)

    root = Path(get_settings().CV_EVAL_DATA_DIR) / DATASET_NAME
    (root / "images").mkdir(parents=True, exist_ok=True)
    entries = []
    with httpx.Client(follow_redirects=True, timeout=60) as client:
        for i, im in enumerate(sorted(chosen, key=lambda x: x["id"]), start=1):
            path = root / "images" / f"{im['id']:012d}.jpg"
            if path.is_file():
                data = path.read_bytes()
            else:
                data = client.get(im["coco_url"]).raise_for_status().content
                path.write_bytes(data)
            decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
            if decoded is None or decoded.shape[1] != im["width"] or decoded.shape[0] != im["height"]:
                raise SystemExit(f"image {im['id']} does not decode to its annotated size")
            boxes = []
            for a in by_image.get(im["id"], []):
                x, y, w, h = a["bbox"]
                boxes.append({"label": _label(a["category_id"]), "coco_category_id": a["category_id"],
                              "x_min": x, "y_min": y, "x_max": x + w, "y_max": y + h, "ignore": bool(a.get("iscrowd"))})
            entries.append({"image_id": im["id"], "file": f"images/{path.name}", "sha256": _sha256(data),
                            "width": im["width"], "height": im["height"], "licence": licences.get(im["license"]),
                            "flickr_url": im.get("flickr_url"), "boxes": boxes})
            if i % 25 == 0 or i == args.count:
                print(f"  {i}/{args.count} images")
    counts = {lbl: sum(1 for e in entries for b in e["boxes"] if b["label"] == lbl and not b["ignore"]) for lbl in ("person", "vehicle")}
    manifest = {
        "dataset_name": DATASET_NAME,
        "dataset_version": f"val2017-seed{args.seed}-n{args.count}",
        "source": "COCO 2017 validation set (https://cocodataset.org); annotations CC BY 4.0, images under per-image Flickr licences",
        "annotations_sha256": ANNOTATIONS_SHA256,
        "sampling": f"uniform random sample of all val2017 images, Python random.Random({args.seed}).sample over images sorted by id",
        "class_mapping": {"person": sorted(PERSON), "vehicle": sorted(VEHICLES)},
        "ground_truth_boxes": counts,
        "images_without_targets": sum(1 for e in entries if not any(not b["ignore"] for b in e["boxes"])),
        "images": entries,
    }
    (root / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {root / 'manifest.json'}: {len(entries)} images, ground truth {counts}, "
          f"{manifest['images_without_targets']} images with no person/vehicle")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
