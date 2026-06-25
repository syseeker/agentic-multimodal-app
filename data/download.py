"""Download small public samples to enrich the sample case with image + audio.

Keeps downloads tiny (a few files). Network access required. Respect each
dataset's license. Writes into data/sample_case/ and updates its manifest.

    python data/download.py
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

CASE = Path("data/sample_case")

# A couple of small, openly-hosted samples. Swap for your preferred sources.
SAMPLES = [
    # (url, filename, modality, label)
    ("https://upload.wikimedia.org/wikipedia/commons/3/3a/Cheque.jpg",
     "evidence_cheque.jpg", "image", "Seized cheque photo (public sample)"),
    ("https://upload.wikimedia.org/wikipedia/commons/c/c8/Example.ogg",
     "statement_audio.ogg", "audio", "Statement audio (public sample)"),
]


def _fetch(url: str, dest: Path) -> bool:
    try:
        urllib.request.urlretrieve(url, dest)  # noqa: S310 (demo download)
        return True
    except Exception as e:
        print(f"  skip {url}: {e}")
        return False


def main() -> None:
    CASE.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((CASE / "manifest.json").read_text())
    existing = {a["asset_id"] for a in manifest["assets"]}

    for url, fname, modality, label in SAMPLES:
        dest = CASE / fname
        if _fetch(url, dest):
            aid = dest.stem
            if aid not in existing:
                manifest["assets"].append(
                    {"asset_id": aid, "modality": modality, "path": fname, "label": label}
                )
                existing.add(aid)
            print(f"  added {modality}: {fname}")

    (CASE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print("Updated manifest. NOTE: image/audio assets need the VLM/audio servers up.")
    print("For Enron/CREMA-D/COCO at scale, see data/README.md.")


if __name__ == "__main__":
    main()
