# HF Space용 Dockerfile — 빌드 시 공개 GitHub repo를 clone(데이터 인덱스 포함).
# HF Space에는 이 파일 + README.md 2개만 두면 되고, 코드·데이터는 GitHub에서 당겨온다.
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

RUN pip install --no-cache-dir -r requirements-ml.txt \
    && mkdir -p /app/.cache/hf && chmod -R 777 /app/.cache

EXPOSE 7860
# 첫 요청에서 bge-m3 로드(HF 허브 내부망이라 빠름). 이후 캐시.
CMD python scripts/run_server.py --host 0.0.0.0 --port ${PORT:-7860}
