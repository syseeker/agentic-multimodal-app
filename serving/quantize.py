"""Offline FP8 quantization with NVIDIA ModelOpt.

Online `--quantization fp8` (in entrypoint.sh) is the zero-setup path. For best
latency / TTFT, pre-quantize once and serve the exported checkpoint:

    python quantize.py --model Qwen/Qwen3-14B --out /models/qwen3-14b-fp8
    # then set MODEL=/models/qwen3-14b-fp8 and QUANT=fp8 in .env

This is intentionally thin — it wraps ModelOpt's PTQ export so the recipe is
visible and auditable rather than hidden in a container layer.
"""
from __future__ import annotations

import argparse


def main() -> None:
    ap = argparse.ArgumentParser(description="FP8 PTQ export via NVIDIA ModelOpt")
    ap.add_argument("--model", required=True, help="HF id or local path")
    ap.add_argument("--out", required=True, help="export dir for the FP8 checkpoint")
    ap.add_argument("--format", default="fp8", choices=["fp8", "nvfp4", "int4_awq"])
    args = ap.parse_args()

    try:
        import modelopt.torch.quantization as mtq  # noqa: F401
        from modelopt.torch.export import export_hf_checkpoint
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError as e:  # pragma: no cover
        raise SystemExit(
            "Install ModelOpt: pip install nvidia-modelopt[hf]\n"
            f"(import error: {e})"
        )

    cfg = {"fp8": mtq.FP8_DEFAULT_CFG,
           "nvfp4": mtq.NVFP4_DEFAULT_CFG,
           "int4_awq": mtq.INT4_AWQ_CFG}[args.format]

    tok = AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.bfloat16, device_map="cuda",
        trust_remote_code=True,
    )

    def _calib(m):
        # Tiny calibration set; replace with domain text for better accuracy.
        for prompt in ["Summarize the key entities in this case.",
                       "List relationships between the parties."]:
            ids = tok(prompt, return_tensors="pt").to("cuda")
            m(**ids)

    mtq.quantize(model, cfg, forward_loop=_calib)
    export_hf_checkpoint(model, export_dir=args.out)
    tok.save_pretrained(args.out)
    print(f"Exported {args.format} checkpoint to {args.out}")


if __name__ == "__main__":
    main()
