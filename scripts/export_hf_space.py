"""Export the committed repository as a Hugging Face Space (Docker SDK).

    python scripts/export_hf_space.py ../aegis-space --github-url https://github.com/<you>/<repo>
    hf upload <you>/<space> ../aegis-space . --repo-type space

Only COMMITTED files are exported (`git archive HEAD`), so nothing local -- .env files, databases,
model weights, node_modules -- can leak into the Space. The export keeps what the root Dockerfile
needs (backend without tests, frontend, Dockerfile, licence) and replaces README.md with
deploy/huggingface/README.md, whose front matter tells Hugging Face to build the Dockerfile and
serve port 7860. See docs/operations/PUBLIC_DEMO.md.
"""
from __future__ import annotations

import argparse
import io
import subprocess
import sys
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = ("Dockerfile", ".dockerignore", "LICENSE", "backend/", "frontend/")
DROP = ("backend/tests/",)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir", type=Path, help="new or empty folder to write the Space into")
    ap.add_argument("--github-url", default="", help="link shown on the Space page")
    args = ap.parse_args()

    out = args.out_dir.resolve()
    if out.exists() and any(out.iterdir()):
        print(f"Refusing: {out} is not empty.")
        return 2
    if out == ROOT or ROOT in out.parents:
        print("Refusing: choose a folder outside the repository.")
        return 2
    dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    if dirty.strip():
        print("Note: uncommitted changes are NOT exported (only HEAD is).")

    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD"], cwd=ROOT, capture_output=True, check=True).stdout
    out.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        for member in tar.getmembers():
            name = member.name
            if not name.startswith(KEEP) or name.startswith(DROP) or not member.isfile():
                continue
            target = out / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(tar.extractfile(member).read())
            count += 1

    readme = (ROOT / "deploy" / "huggingface" / "README.md").read_text(encoding="utf-8")
    link = args.github_url.strip() or "(add the GitHub link with --github-url)"
    (out / "README.md").write_text(readme.replace("__GITHUB_URL__", link), encoding="utf-8")
    print(f"Exported {count} files + README.md to {out}")
    print("Next:  hf auth login   then   hf upload <you>/<space> \"%s\" . --repo-type space" % out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
