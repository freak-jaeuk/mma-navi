# 라이브 데모 배포 가이드 (GPU·인증키 불필요)

심사위원이 클론·GPU 없이 "나의 병역 준비 카드"를 바로 볼 수 있게 하는 배포법.
데이터 인덱스가 저장소에 프리빌드로 포함되어 `MMA_SERVICE_KEY` 없이 동작한다.

## 모드 비교

| 모드 | 백분위 | 특기 랭킹 | 상담 | 무게 | 호스트 |
|---|---|---|---|---|---|
| `mock` | 실데이터 | lexical(약) | 데모응답 | 초경량(모델無) | Render/Railway/Fly 무료 |
| `bge-extractive` | 실데이터 | **bge-m3 semantic** | 근거검색 | bge-m3 CPU(~2GB RAM) | **HF Spaces CPU 16GB(무료)** |
| `bge-llm` | 실데이터 | semantic | 생성(Qwen) | GPU 필요 | 로컬/GPU 서버 |

헤드라인 수치(정확도 0.909)는 `bge-llm`(GPU) 기준 — `eval/rag_e2e_report.json`에 파일로 커밋됨.
라이브 데모는 GPU 없는 `bge-extractive`(semantic 유지) 또는 `mock`으로 충분하다.

## A. Hugging Face Spaces (권장 — 무료·GPU無·특기 semantic 유지)

1. https://huggingface.co/new-space → **Docker** SDK, 하드웨어 **CPU basic(무료, 16GB)**.
2. 이 저장소를 Space에 push(또는 GitHub 연동). `Dockerfile`이 자동 사용됨.
3. Space의 `README.md`를 `deploy/huggingface_README.md` 내용으로 교체(제목·emoji·`app_port: 7860` frontmatter 필요).
4. 빌드 후 첫 요청에서 bge-m3(~2GB) 지연 로드로 수십 초 소요, 이후 캐시됨.
5. 나온 URL을 기획서 '제품/서비스 등록정보 → 웹' 칸에 기입하고 서비스형태 '웹' 체크.

## B. Render (폴백 — 초경량·즉시 기동, 특기는 lexical)

1. https://dashboard.render.com → New → **Blueprint** → 이 저장소 선택.
2. `render.yaml`이 `mock` 모드로 자동 배포(모델 로드 없음, 즉시 기동).
3. 무료 플랜은 유휴 시 슬립 → 첫 접속만 수십 초. 데모엔 무방.

## 로컬에서 배포 모드 그대로 확인

```bash
# mock (키·GPU·모델 전부 불필요)
MMA_RAG=mock python scripts/run_server.py --host 0.0.0.0 --port 8000

# bge-extractive (특기 semantic, CPU, 키 불필요)
pip install -r requirements-ml.txt
MMA_RAG=bge-extractive MMA_TEUKGI_SEM=1 MMA_EMBED_DEVICE=cpu \
  python scripts/run_server.py --host 0.0.0.0 --port 8000
```

→ http://localhost:8000 접속. 입력 1회 → 카드(백분위·특기·로드맵·상담).
