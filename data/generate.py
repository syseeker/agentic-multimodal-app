"""Generate synthetic case material with NeMo Data Designer.

Produces extra WhatsApp-style chats and statement transcripts so the graph has
more parties to analyze. Falls back to a built-in template generator if Data
Designer isn't installed, so the script always produces usable output.

    python data/generate.py --out data/generated/case_b --parties 6
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

NAMES = ["John Tan", "Mei Ling", "Ah Kow", "Rajesh", "Samad", "Wei Jie",
         "Siti", "David Lim", "Chen Hui", "Farid"]
ACTIONS = [
    "{a}: shipment cleared, warehouse unit {n}",
    "{a}: transfer {amt}k to DBS 0{acct}",
    "{a}: cash ready, counting now",
    "{a}: buyer {b} wants {q} more boxes",
    "{a}: use the boat from Batam, no Penang",
    "{a}: pay the driver {pay} cash, dont transfer",
]


def _data_designer(out: Path, parties: int) -> bool:
    """Try the real NeMo Data Designer path. Returns True on success."""
    try:
        from nemo_data_designer import DataDesigner  # type: ignore
    except Exception:
        return False
    # Reference shape; configure columns/prompts per the data-designer skill.
    dd = DataDesigner()
    dd.add_generated_column(
        name="message",
        prompt=(
            "Write one line of a covert logistics WhatsApp chat between "
            f"{parties} fictional parties hinting at money transfers and shipments."
        ),
    )
    df = dd.generate(num_records=24)
    lines = [f"[2025-03-0{1 + i % 7} 21:{10 + i:02d}] {row}"
             for i, row in enumerate(df["message"].tolist())]
    (out / "whatsapp_groupchat.txt").write_text("\n".join(lines))
    return True


def _template(out: Path, parties: int) -> None:
    people = random.sample(NAMES, k=min(parties, len(NAMES)))
    lines = ["# SYNTHETIC (template fallback) — fictional demo data"]
    for i in range(20):
        a = random.choice(people)
        b = random.choice([p for p in people if p != a])
        line = random.choice(ACTIONS).format(
            a=a, b=b, n=random.randint(1, 9), amt=random.choice([15, 25, 40, 60]),
            acct=random.randint(10000000, 99999999), q=random.randint(2, 10),
            pay=random.choice([500, 800, 1200]),
        )
        lines.append(f"[2025-03-0{1 + i % 7} 21:{10 + i:02d}] {line}")
    (out / "whatsapp_groupchat.txt").write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/generated/case_b")
    ap.add_argument("--parties", type=int, default=6)
    ap.add_argument("--objective", default="Map parties and money flows.")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if not _data_designer(out, args.parties):
        print("NeMo Data Designer not available — using template fallback.")
        _template(out, args.parties)

    manifest = {
        "case_id": out.name,
        "objective": args.objective,
        "assets": [
            {"asset_id": "wa-gen", "modality": "text",
             "path": "whatsapp_groupchat.txt", "label": "Generated chat"}
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote case to {out}")


if __name__ == "__main__":
    main()
