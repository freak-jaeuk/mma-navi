# 병역 길잡이 — 라이브 데모 이미지 (GPU 불필요)
# 기본: bge-extractive + 특기 semantic 랭킹 (CPU). Hugging Face Spaces(CPU 16GB) 권장.
# 인증키(MMA_SERVICE_KEY) 불필요 — 데이터 인덱스가 이미지에 프리빌드로 포함됨.
# 더 가벼운 mock 모드로 띄우려면 MMA_RAG=mock 로 오버라이드(모델 로드 없음).
FROM python:3.11-slim

WORKDIR /app

# HF/transformers 캐시를 쓰기가능 경로로(Spaces 비루트 환경 대비)
ENV HF_HOME=/app/.cache/hf \
    TRANSFORMERS_CACHE=/app/.cache/hf \
    MMA_RAG=bge-extractive \
    MMA_TEUKGI_SEM=1 \
    MMA_EMBED_DEVICE=cpu \
    PORT=7860

COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements-ml.txt

COPY . .
RUN mkdir -p /app/.cache/hf && chmod -R 777 /app/.cache

EXPOSE 7860
# 첫 요청에서 bge-m3(약 2GB) 지연 로드 — Spaces CPU 기준 수십 초. 이후 캐시됨.
CMD ["sh", "-c", "python scripts/run_server.py --host 0.0.0.0 --port ${PORT:-7860}"]
