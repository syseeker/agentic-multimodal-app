# vLLM OpenAI-compatible server, FP8-capable, multi-arch aware.
#
# x86_64 (RTX PRO 6000 dev): the public vllm/vllm-openai image works.
# arm64/sbsa (GB10 deploy):  override BASE with the NGC sbsa vLLM image, e.g.
#   docker build --build-arg BASE=nvcr.io/nvidia/vllm:<sbsa-tag> ...
# Pick a tag with Blackwell (sm_121) kernels. See docs/DEPLOY_GB10.md.
ARG BASE=vllm/vllm-openai:latest
FROM ${BASE}

# ModelOpt for offline FP8 quantization recipes (serving/quantize.py).
RUN pip install --no-cache-dir "nvidia-modelopt" || \
    echo "modelopt install skipped (online --quantization fp8 still available)"

COPY entrypoint.sh /entrypoint.sh
COPY quantize.py   /quantize.py
RUN chmod +x /entrypoint.sh

# vLLM image sets its own ENTRYPOINT; override it with ours.
ENTRYPOINT ["/entrypoint.sh"]
