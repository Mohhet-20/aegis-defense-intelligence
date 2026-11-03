"""Object-detection evaluation on REAL images: the COCO val2017 subset built by
scripts/fetch_eval_data.py.

Each image's SHA-256 is checked against the manifest before use. Predictions go
through the same postprocessing (validation, confidence floor, NMS, per-frame cap)
as production inference, so the numbers describe what the platform would store.

Matching follows the usual COCO/VOC protocol at one IoU threshold: per image and
class, predictions are taken in descending confidence and each is matched to the
unmatched ground-truth box with the highest IoU >= threshold (true positive);
otherwise, if it overlaps a crowd ("ignore") region by >= threshold it is
ignored, else it is a false positive. AP is the 101-point interpolated area under
the precision/recall curve (as in the COCO evaluator, at a single IoU).
Precision/recall/F1 are also reported at the operating confidence threshold the
platform uses by default.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.cv import postprocessing
from app.cv.adapters.base import CVModelAdapter

DATASET_NAME = "coco_val2017_subset"
CLASSES = ("person", "vehicle")
CANDIDATE_CONFIDENCE = 0.05  # keep low-confidence candidates so the PR curve is complete


class DatasetUnavailable(RuntimeError):
    """The evaluation set is not installed or failed verification; the message says how to fix it."""


@dataclass(frozen=True)
class Box:
    label: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float
    confidence: float = 1.0
    ignore: bool = False


def dataset_root() -> Path:
    return Path(get_settings().CV_EVAL_DATA_DIR) / DATASET_NAME


def load_manifest() -> dict:
    path = dataset_root() / "manifest.json"
    if not path.is_file():
        raise DatasetUnavailable("The COCO evaluation subset is not installed. Run `python scripts/fetch_eval_data.py` in backend/.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("dataset_name") != DATASET_NAME or not manifest.get("images"):
        raise DatasetUnavailable("The COCO evaluation manifest is malformed; re-run scripts/fetch_eval_data.py.")
    return manifest


def iou(a: Box, b: Box) -> float:
    iw = max(0.0, min(a.x_max, b.x_max) - max(a.x_min, b.x_min))
    ih = max(0.0, min(a.y_max, b.y_max) - max(a.y_min, b.y_min))
    inter = iw * ih
    union = (a.x_max - a.x_min) * (a.y_max - a.y_min) + (b.x_max - b.x_min) * (b.y_max - b.y_min) - inter
    return inter / union if union > 0 else 0.0


def match_image(preds: list[Box], gts: list[Box], iou_threshold: float) -> tuple[list[tuple[float, bool, float]], int]:
    """For ONE class in ONE image. Returns ([(confidence, is_true_positive, iou)] for
    every non-ignored prediction, number of non-ignored ground-truth boxes)."""
    real = [g for g in gts if not g.ignore]
    crowd = [g for g in gts if g.ignore]
    used = [False] * len(real)
    out: list[tuple[float, bool, float]] = []
    for p in sorted(preds, key=lambda b: b.confidence, reverse=True):
        best, best_iou = -1, iou_threshold
        for i, g in enumerate(real):
            if not used[i]:
                v = iou(p, g)
                if v >= best_iou:
                    best, best_iou = i, v
        if best >= 0:
            used[best] = True
            out.append((p.confidence, True, best_iou))
        elif any(iou(p, c) >= iou_threshold for c in crowd):
            continue  # matched a crowd region: neither TP nor FP
        else:
            out.append((p.confidence, False, 0.0))
    return out, len(real)


def average_precision(scored: list[tuple[float, bool, float]], n_gt: int) -> float | None:
    """101-point interpolated AP; None when there is no ground truth (undefined, not 0)."""
    if n_gt == 0:
        return None
    if not scored:
        return 0.0
    ordered = sorted(scored, key=lambda s: s[0], reverse=True)
    tp = np.cumsum([1 if s[1] else 0 for s in ordered])
    fp = np.cumsum([0 if s[1] else 1 for s in ordered])
    recall = tp / n_gt
    precision = tp / np.maximum(tp + fp, 1)
    envelope = np.maximum.accumulate(precision[::-1])[::-1]  # precision made monotonically non-increasing
    points = []
    for r in np.linspace(0.0, 1.0, 101):
        idx = np.searchsorted(recall, r, side="left")
        points.append(float(envelope[idx]) if idx < len(envelope) else 0.0)
    return float(np.mean(points))


def _rates(tp: int, fp: int, fn: int) -> dict:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    f1 = 2 * precision * recall / (precision + recall) if precision and recall else (0.0 if precision is not None and recall is not None else None)
    return {"precision": precision, "recall": recall, "f1": f1}


def evaluate(adapter: CVModelAdapter, *, sample_count: int | None = None, iou_threshold: float = 0.5,
             operating_threshold: float | None = None) -> dict:
    import cv2

    manifest = load_manifest()
    operating = get_settings().CV_DEFAULT_CONFIDENCE_THRESHOLD if operating_threshold is None else operating_threshold
    images = manifest["images"][: sample_count or len(manifest["images"])]
    scored: dict[str, list[tuple[float, bool, float]]] = {c: [] for c in CLASSES}
    n_gt = {c: 0 for c in CLASSES}
    elapsed = 0.0
    root = dataset_root()
    for entry in images:
        data = (root / entry["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise DatasetUnavailable(f"Image {entry['image_id']} does not match its recorded SHA-256; re-run scripts/fetch_eval_data.py.")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        h, w = image.shape[:2]
        started = time.perf_counter()
        raw = adapter.predict(image)
        elapsed += time.perf_counter() - started
        kept, _ = postprocessing.postprocess(raw, frame_width=w, frame_height=h, confidence_threshold=CANDIDATE_CONFIDENCE)
        preds = [Box(d.class_label, d.bbox_x_min * w, d.bbox_y_min * h, d.bbox_x_max * w, d.bbox_y_max * h, d.confidence) for d in kept]
        gts = [Box(b["label"], b["x_min"], b["y_min"], b["x_max"], b["y_max"], ignore=b["ignore"]) for b in entry["boxes"]]
        for c in CLASSES:
            s, n = match_image([p for p in preds if p.label == c], [g for g in gts if g.label == c], iou_threshold)
            scored[c].extend(s)
            n_gt[c] += n

    per_class, totals = {}, {"tp": 0, "fp": 0, "fn": 0}
    matched_ious: list[float] = []
    for c in CLASSES:
        at_op = [s for s in scored[c] if s[0] >= operating]
        tp = sum(1 for s in at_op if s[1])
        fp = len(at_op) - tp
        fn = n_gt[c] - tp
        matched_ious += [s[2] for s in at_op if s[1]]
        per_class[c] = {"ground_truth": n_gt[c], "tp": tp, "fp": fp, "fn": fn, "ap50": average_precision(scored[c], n_gt[c]), **_rates(tp, fp, fn)}
        totals["tp"] += tp
        totals["fp"] += fp
        totals["fn"] += fn
    aps = [v["ap50"] for v in per_class.values() if v["ap50"] is not None]
    return {
        "dataset_name": manifest["dataset_name"],
        "dataset_version": manifest["dataset_version"],
        "is_synthetic": False,
        "sample_count": len(images),
        "iou_threshold": iou_threshold,
        "operating_confidence_threshold": operating,
        "per_class": per_class,
        "overall": {**totals, **_rates(totals["tp"], totals["fp"], totals["fn"]),
                    "map50": float(np.mean(aps)) if aps else None,
                    "mean_iou_of_matches": float(np.mean(matched_ious)) if matched_ious else None},
        "mean_inference_ms_per_image": round(1000 * elapsed / max(len(images), 1), 2),
        "protocol": "greedy per-image matching by confidence at IoU threshold; crowd regions ignored; 101-point interpolated AP; "
                    "predictions pass through the production postprocessing (validation, NMS, per-frame cap)",
        "source": manifest.get("source"),
    }
