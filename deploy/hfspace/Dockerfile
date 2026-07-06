# HF Space용 Dockerfile — 빌드 시 GitHub repo clone + bge-m3 미리 캐시(런타임 다운로드 제거).
FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
RUN git clone --depth 1 https://github.com/freak-jaeuk/mma-navi.git .

ENV HF_HOME=/app/.cache/hf \
    TRANSFORMERS_CACHE=/app/.cache/hf \
    MMA_RAG=bge-extractive \
    MMA_TEUKGI_SEM=1 \
    MMA_EMBED_DEVICE=cpu \
    PORT=7860

RUN pip install --no-cache-dir -r requirements-ml.txt
# bge-m3(약 2GB)를 빌드 때 이미지에 캐시 — HF 런타임 egress 없이 동작
RUN python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-m3')"
# 이후 런타임은 오프라인 캐시만 사용(연결 시도로 인한 지연·실패 방지)
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
RUN mkdir -p /app/.cache/hf && chmod -R 777 /app/.cache

EXPOSE 7860
CMD python scripts/run_server.py --host 0.0.0.0 --port ${PORT:-7860}
