"""Pinned descriptions of pretrained model files: where they come from, under which
license, and the SHA-256 every copy must match before it is loaded.

scripts/fetch_models.py downloads and verifies them into settings.CV_MODEL_DIR;
the adapters verify again on first load. A file that is missing or whose hash
differs is never loaded -- the adapter raises ModelAssetsUnavailable instead.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.core.config import get_settings


class ModelAssetsUnavailable(RuntimeError):
    """Weights are not installed (or failed verification). The message says how to fix it."""


@dataclass(frozen=True)
class AssetFile:
    name: str           # file name inside the model's directory
    sha256: str
    source_url: str     # where scripts/fetch_models.py gets it
    archive_member: str | None = None  # path inside a .tar.gz download, if any
    archive_sha256: str | None = None  # pinned hash of that download


@dataclass(frozen=True)
class ModelAssets:
    key: str
    directory: str
    license: str
    provenance: str
    files: tuple[AssetFile, ...]

    def path(self, name: str) -> Path:
        return Path(get_settings().CV_MODEL_DIR) / self.directory / name


SSD_MOBILENET_V1_COCO = ModelAssets(
    key="ssd_mobilenet_v1_coco",
    directory="ssd_mobilenet_v1_coco_2017_11_17",
    license="Apache-2.0 (TensorFlow Object Detection API model zoo; graph config from opencv_extra, Apache-2.0)",
    provenance="SSD with a MobileNet v1 backbone trained on COCO 2017 by the TensorFlow Object Detection API team (release 2017-11-17).",
    files=(
        AssetFile(
            name="frozen_inference_graph.pb",
            sha256="cb3ce31b95a54162c25d951780a740a8767e6f9987298ec53d3146f0a5506858",  # pragma: allowlist secret (public SHA-256 pin)
            source_url="http://download.tensorflow.org/models/object_detection/ssd_mobilenet_v1_coco_2017_11_17.tar.gz",
            archive_member="ssd_mobilenet_v1_coco_2017_11_17/frozen_inference_graph.pb",
            archive_sha256="da29bfb388fd7384f0c858a72c0af3976c63b96912f682a2aa94c129f17b18c9",  # pragma: allowlist secret (public SHA-256 pin)
        ),
        AssetFile(
            name="ssd_mobilenet_v1_coco_2017_11_17.pbtxt",
            sha256="c15a9ac2df5cdb379e3a294adc73f13c796da8d682d763f4ec15831af1e11923",  # pragma: allowlist secret (public SHA-256 pin)
            source_url="https://raw.githubusercontent.com/opencv/opencv_extra/4.x/testdata/dnn/ssd_mobilenet_v1_coco_2017_11_17.pbtxt",
        ),
    ),
)

ALL_ASSETS = {SSD_MOBILENET_V1_COCO.key: SSD_MOBILENET_V1_COCO}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verified_paths(assets: ModelAssets) -> dict[str, Path]:
    """Paths of every file, after checking each exists and matches its pinned hash."""
    out: dict[str, Path] = {}
    for f in assets.files:
        p = assets.path(f.name)
        if not p.is_file():
            raise ModelAssetsUnavailable(
                f"Model '{assets.key}' is not installed (missing {f.name}). "
                "Run `python scripts/fetch_models.py` in backend/ to download and verify it."
            )
        if sha256_file(p) != f.sha256:
            raise ModelAssetsUnavailable(
                f"Model '{assets.key}' failed integrity verification ({f.name} does not match its pinned SHA-256). "
                "Delete the file and run `python scripts/fetch_models.py` again."
            )
        out[f.name] = p
    return out


def installed(assets: ModelAssets) -> bool:
    try:
        verified_paths(assets)
        return True
    except ModelAssetsUnavailable:
        return False
