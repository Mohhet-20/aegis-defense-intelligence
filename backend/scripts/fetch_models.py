"""Download and verify pretrained model weights into CV_MODEL_DIR (default backend/model_artifacts).

    python scripts/fetch_models.py                      # all models
    python scripts/fetch_models.py --from-dir D:\\dl     # offline: use already-downloaded files
    python scripts/fetch_models.py --check              # verify what is installed, download nothing

Every download is checked against the SHA-256 pinned in app/cv/model_assets.py;
from an archive only the one expected member is extracted (never the whole
archive, never a path outside the target). Files are written to a temporary name
and moved into place only after verification. Weights are never committed to git.
Exit status 0 = every model installed and verified.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tarfile
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import httpx  # noqa: E402

from app.cv.model_assets import ALL_ASSETS, AssetFile, ModelAssets, installed, sha256_file  # noqa: E402


def _download(url: str, dest: Path) -> None:
    with httpx.stream("GET", url, follow_redirects=True, timeout=120) as r:
        r.raise_for_status()
        with dest.open("wb") as fh:
            for chunk in r.iter_bytes(1 << 20):
                fh.write(chunk)


def _source_file(url: str, from_dir: Path | None, tmp: Path) -> Path:
    if from_dir is not None:
        local = from_dir / url.rsplit("/", 1)[-1]
        if not local.is_file():
            raise SystemExit(f"--from-dir: {local} not found (expected the file named in {url})")
        return local
    dest = tmp / url.rsplit("/", 1)[-1]
    if not dest.exists():
        print(f"  downloading {url}")
        _download(url, dest)
    return dest


def _install_file(assets: ModelAssets, f: AssetFile, from_dir: Path | None, tmp: Path) -> None:
    target = assets.path(f.name)
    if target.is_file() and sha256_file(target) == f.sha256:
        print(f"  {f.name}: already installed and verified")
        return
    src = _source_file(f.source_url, from_dir, tmp)
    # Stage beside the target so the final os.replace is an atomic same-volume rename.
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_name(f.name + ".partial")
    if f.archive_member:
        if f.archive_sha256 and sha256_file(src) != f.archive_sha256:
            raise SystemExit(f"  {src.name}: SHA-256 mismatch for the downloaded archive -- refusing to extract")
        with tarfile.open(src, "r:gz") as tar:
            member = tar.getmember(f.archive_member)  # KeyError if absent: never extract anything else
            if not member.isfile():
                raise SystemExit(f"  {f.archive_member} in {src.name} is not a regular file")
            with tar.extractfile(member) as fin, staged.open("wb") as fout:  # type: ignore[union-attr]
                shutil.copyfileobj(fin, fout)
    else:
        shutil.copyfile(src, staged)
    digest = sha256_file(staged)
    if digest != f.sha256:
        staged.unlink(missing_ok=True)
        raise SystemExit(f"  {f.name}: SHA-256 mismatch (got {digest}) -- not installed")
    os.replace(staged, target)
    print(f"  {f.name}: installed, SHA-256 verified")


def _write_provenance(assets: ModelAssets) -> None:
    info = {
        "model": assets.key, "license": assets.license, "provenance": assets.provenance,
        "files": [{"name": f.name, "sha256": f.sha256, "source_url": f.source_url, "archive_member": f.archive_member} for f in assets.files],
    }
    path = assets.path("PROVENANCE.json")
    path.write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-dir", type=Path, default=None)
    ap.add_argument("--check", action="store_true")
    ap.add_argument("models", nargs="*", default=sorted(ALL_ASSETS))
    args = ap.parse_args()
    ok = True
    for key in args.models:
        assets = ALL_ASSETS.get(key)
        if assets is None:
            print(f"unknown model '{key}'; known: {sorted(ALL_ASSETS)}")
            return 2
        print(f"{key} ({assets.license})")
        if args.check:
            good = installed(assets)
            print("  installed and verified" if good else "  NOT installed (or failed verification)")
            ok &= good
            continue
        with tempfile.TemporaryDirectory(prefix="aegis-models-") as tmp:
            for f in assets.files:
                _install_file(assets, f, args.from_dir, Path(tmp))
        _write_provenance(assets)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
