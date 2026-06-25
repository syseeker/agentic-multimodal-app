# data/ — mock case material

No real case data ships here. We use **synthetic** + **public** data so the demo
is reproducible and shareable.

## Committed, ready to run
[`sample_case/`](sample_case/) — a fully synthetic, **text-only** case (WhatsApp
group export + a statement transcript). Runs without the VLM/audio servers:

```bash
ama run --case data/sample_case
```

[`demos/`](demos/) — **five demo cases**, each showcasing an agentic capability
the old linear flow couldn't do (multimodal correlation, contradiction detection,
hidden-kingpin centrality, duress/paralinguistics, network community detection).
See the table in [`../QUICKSTART.md`](../QUICKSTART.md#demo-cases--the-agentic-showcase).

## Add multimodal assets

```bash
python data/generate.py     # synthetic chats/statements via NeMo Data Designer
python data/download.py      # small public samples (image / audio / text)
```

Generated assets land in `data/generated/` (git-ignored).

### Public datasets used (downloaded, not committed)
| Modality | Dataset | Use |
|---|---|---|
| Text / relations | **Enron email** (sample) | realistic entity/relationship graph |
| Audio / emotion | **CREMA-D** or **RAVDESS** (clips) | paralinguistic sentiment (MERaLiON-3) |
| Image | **COCO** / **Open Images** (sample) | OCR/scene extraction (Qwen3-VL) |

Each downloader takes only a handful of files. Respect each dataset's license.

## Manifest format
A case directory contains `manifest.json`:
```json
{
  "case_id": "sample-case",
  "objective": "…",
  "assets": [
    { "asset_id": "wa-1", "modality": "text",  "path": "chat.txt",   "label": "…" },
    { "asset_id": "img-1","modality": "image", "path": "photo.jpg",  "label": "…" },
    { "asset_id": "aud-1","modality": "audio", "path": "stmt.wav",   "label": "…" }
  ]
}
```
