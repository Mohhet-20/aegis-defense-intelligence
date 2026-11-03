"""A small, clearly-labelled SYNTHETIC evaluation fixture (Phase 4,
Section 10). No real labelled operational dataset exists in this
repository yet, so this module generates one deterministically at
evaluation time -- never from a downloaded or externally-fetched
dataset ("no unrestricted remote media fetching" applies
here too) -- rather than shipping committed binary image fixtures.

Every sample is a solid-color background with exactly one filled
rectangle drawn at a position derived from `numpy.random.RandomState(
seed=index)`, so the SAME `sample_count` always produces the SAME
images and the SAME ground truth across runs and across machines --
required for `evaluated_at`-stamped metrics to be meaningfully
reproducible at all.

This is a deliberately easy, geometric fixture for exercising the
evaluation PIPELINE's correctness (IoU matching, precision/recall/F1
arithmetic, traceability) -- it is explicitly NOT a claim about
real-world detection accuracy on real imagery. See
docs/ml/MODEL_EVALUATION.md.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

IMAGE_SIZE = 240
GROUND_TRUTH_CLASS_LABEL = "mock_object"


@dataclass(frozen=True)
class GroundTruthBox:
    class_label: str
    x_min: float
    y_min: float
    x_max: float
    y_max: float


@dataclass(frozen=True)
class FixtureSample:
    index: int
    image_bgr: np.ndarray
    ground_truth: GroundTruthBox


def generate(sample_count: int) -> list[FixtureSample]:
    samples: list[FixtureSample] = []
    for index in range(sample_count):
        rng = np.random.RandomState(seed=index)
        image = np.full((IMAGE_SIZE, IMAGE_SIZE, 3), 30, dtype=np.uint8)  # dark background

        box_w = int(rng.randint(40, 90))
        box_h = int(rng.randint(40, 90))
        x_min = int(rng.randint(0, IMAGE_SIZE - box_w))
        y_min = int(rng.randint(0, IMAGE_SIZE - box_h))
        x_max, y_max = x_min + box_w, y_min + box_h

        image[y_min:y_max, x_min:x_max] = (200, 200, 60)  # a bright rectangle -- the one "object" in frame

        samples.append(
            FixtureSample(
                index=index,
                image_bgr=image,
                ground_truth=GroundTruthBox(GROUND_TRUTH_CLASS_LABEL, float(x_min), float(y_min), float(x_max), float(y_max)),
            )
        )
    return samples
