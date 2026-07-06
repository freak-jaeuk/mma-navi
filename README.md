# 병역준비 AI 내비게이터

> 근거가 없으면 답하지 않는 병역 준비 AI
> 2026 병무청·방위사업청·질병관리청 합동 공공데이터·AI 경진대회 (제품·서비스 개발 부문)

병무청 공공데이터를 근거로 **병역판정 준비·모집병 특기 탐색·병역진로 상담·민원 응답**을
지원한다. AI는 병역처분을 **예측하지 않고**, 근거가 부족하면 **답변을 거부**한다.

## 🚀 바로 실행 (인증키·GPU·모델 다운로드 불필요)

```bash
pip install -r requirements.txt
python scripts/run_server.py            # http://127.0.0.1:8000 — 입력 1회 → 준비 카드 한 장
```

데이터 인덱스가 저장소에 포함되어 **키 없이 즉시** 백분위·특기·로드맵·상담(데모)이 동작한다.
특기 **의미(bge-m3) 랭킹**까지 켜려면(GPU 불필요, CPU):
`pip install -r requirements-ml.txt && MMA_RAG=bge-extractive MMA_TEUKGI_SEM=1 python scripts/run_server.py`

- **라이브 데모**: `[배포 후 기입]` (무료·GPU無 배포법 → [`deploy/`](deploy/README.md))
- **데모 영상**: `[업로드 후 기입]` (유튜브 미등록 → 샷 리스트 [`docs/데모_영상_시나리오.md`](docs/데모_영상_시나리오.md))
- **측정 결과**: [`eval/RESULTS.md`](eval/RESULTS.md) (dev/held-out 수치를 파일로 — 안 돌려도 확인)

## 화면

입력 1회 → "나의 병역 준비 카드"(①건강 ②특기 ③로드맵 ④상담). 캡처는 [`docs/screenshots/`](docs/screenshots/)에 둔다.

| 화면 | 파일 |
|---|---|
| 준비 카드(백분위·특기·로드맵) | `docs/screenshots/card.png` |
| 상담 — 위험질문 자동 거부 + 우회로 | `docs/screenshots/refuse.png` |

> 이미지가 아직 없으면 위 '바로 실행'으로 띄워 직접 확인. 정적 UI는 [`web/`](web/)에 있다.

## 문서
- [기능명세서](기능명세서.md)
- [데이터 및 기존 수상작](데이터_및_기존수상작.md)

## 구조
```
src/mma_navi/        # 코어 패키지
  percentile.py      # 결정론 백분위 엔진 (환각 구조적 불가, gap-aware abstain)
  dataio.py          # 분포 로딩(CSV) + microdata→히스토그램 빌더
  mma_api.py         # data.go.kr 오픈API 클라이언트(키 redaction 포함)
  rag/               # 상담 RAG + 거부 게이트 (AI30 핵심축)
    gates.py         #   의도/근거/일관성 게이트 + 거부 taxonomy
    pipeline.py      #   오케스트레이션(답하거나 거부)
    mocks.py         #   오프라인 테스트용 mock retriever/LLM
    embed.py         #   bge-m3 임베딩(transformers 직접 로드, CLS+정규화)
    retriever.py     #   BgeRetriever(실 의미검색) + bge-reranker-v2-m3(옵션)
    llm.py           #   LocalLLM(로컬 Qwen, 근거만 생성·예측 금지 프롬프트)
  recommend/         # 모집병 특기 추천
    teukgi.py        #   자격충족(결정론·등급/점수검증) + 관련도 + 비보유 가드
    index.py         #   특기 단위 인덱스 매처(자격→특기, ok/본인확인/미달 분리)
    semantic.py      #   bge-m3 의미 관련도(494특기 임베딩+지문캐시) — lexical 대체
    dataio.py        #   3066750 로더
  classify.py        # 민원 질문 5범주 분류기(F5)
  eval/metrics.py    # P/R/F1 (AI30 증거물)
  app/               # 통합 데모 (4코어 → 웹)
    service.py       #   서비스 레이어 + build_roadmap(F4 접착제)·roadmap_report·classify_query
    server.py        #   FastAPI 라우트(/api/roadmap|consult|classify|percentile|teukgi|metrics)
web/                 # 단일 페이지 "나의 병역 준비 카드"(입력1회→백분위+특기+로드맵+상담, vanilla JS)
  index.html         #   단일 입력 + 카드 섹션(①건강 ②특기 ③로드맵 ④상담) + 담당자 모드
  app.js             #   runCard(/api/roadmap 1회)·거부 우회로(alt→섹션 점프)·인쇄·메트릭 강등
  style.css          #   카드/로드맵 타임라인/인쇄 @media print
data/
  distributions_real.csv   # 실데이터 분포(전국+14지방청) — fetch_and_build 산출
  teukgi_index.json        # 특기 인덱스(494특기) — 데모용 프리빌드 포함(키 없이 실행)
  cache/teukgi_emb.npz     # 특기 bge-m3 임베딩 캐시(semantic, 포함) / *.csv microdata는 gitignore
  fixtures/                # 합성 검증 데이터(키 없을 때 fallback)
  kb_demo.json             # 상담 RAG 데모 KB(시드) — Phase 1에서 bge-m3 문서로 교체
eval/                # 골드셋(독립 생성·검증) + 메트릭 리포트
  refusal_set/classify_set.json    # dev(튜닝 사용)
  refusal_test/classify_test.json  # held-out(미사용, 일반화)
tests/               # 자체 테스트 (99개+bge통합3: 엔진15+API6+RAG16+추천10+인덱스10+평가8+서비스34 / test_rag_real는 MMA_TEST_BGE=1)
scripts/             # 데모/프로브/수집/평가(run_eval)/서버(run_server)
```

## 실행
```bash
python tests/test_percentile.py        # 엔진 테스트 (15/15)
python tests/test_api.py               # API 파서/보안 테스트 (6/6)
python scripts/demo_percentile.py      # 백분위 + 거부 데모 (실데이터)

# 통합 데모 "나의 병역 준비 카드" (입력 1회 → 백분위+특기+로드맵+상담 한 장)
python scripts/run_server.py           # http://127.0.0.1:8000 (원격: --host 0.0.0.0)
python scripts/run_eval.py             # AI30 메트릭(intent 거부게이트+분류기)

# 실 RAG(bge-m3 + 로컬 Qwen) 연결 — 모델은 로컬 캐시 사용(오프라인)
MMA_RAG=bge-llm MMA_EMBED_DEVICE=cpu MMA_LLM_DEVICE=cuda:0 python scripts/run_server.py
MMA_RAG=bge-llm MMA_EMBED_DEVICE=cpu MMA_LLM_DEVICE=cuda:0 python scripts/run_rag_eval.py  # end-to-end 평가
#   MMA_RAG: mock(기본) | bge-extractive(검색만·환각0) | bge-llm(검색+생성)

# 실데이터 수집/재빌드 (MMA_SERVICE_KEY 필요, 네트워크)
python scripts/probe_sinche_api.py     # API 스키마 확인
python scripts/fetch_and_build.py      # 전체 수집→분포 빌드 (--refetch로 재수집)
```

## 진행 상태
- [x] **Phase 0-1** 결정론 백분위 엔진 + 절단/gap 거부 + **실데이터(3064321, 96,360명, 14지방청)** + Codex 통과
- [x] **Phase 0-2** 상담 RAG + **거부 게이트**(개인판정/의료진단/합격예측/근거부족 + 자기일관성·근거율·부실답변 가드) + Codex 통과
- [x] **Phase 0-3** 모집병 특기 추천 — **실데이터(3066750, 1.36M행→494특기)** 인덱스, 자격→특기 결정론 매칭(등급/점수검증·본인확인 분리) + 관련도 + Codex 통과
- [x] **Phase 0-4** 거부·분류 평가셋(독립 생성·검증 골드셋) + P/R/F1 메트릭 + **dev/held-out 분리 측정** + Codex 통과
- [x] **Phase 0-5** 통합 데모(1차) — FastAPI + 웹으로 4코어 연결, 서비스 레이어 분리 + Codex 통과(인덱스 동시성 레이스 수정)
- [x] **Phase 0-6** **단일 카드 재설계** — 4탭 폐기→"나의 병역 준비 카드"(입력1회→백분위+특기+**로드맵**+상담). 설계패널(5안→3심사→합성)로 결정. **경로생성(F4) 접착제 복원**(build_roadmap이 내 결과 인용)·**거부=우회로**(alt→섹션 점프)·**AI신뢰도 강등**(사용자 전면→푸터/담당자 모드) + Codex 통과(build_roadmap KeyError·unknown 오표기 수정)
- [x] **Phase 1** 실 RAG 연결 — **bge-m3 임베딩 검색**(MockRetriever 대체, 한국어 조사 문제 해소)·**로컬 Qwen 생성**(근거만·예측금지)·bge-reranker(옵션)·**B2G 14지방청 히트맵(F7)**·**end-to-end RAG 평가** + Codex 통과(lazy 폴백 구멍·device/dtype·pytest 수집 가드)
- [x] **Phase 1+** 3개 갭 보강 — ① **특기 의미매칭**(bge-m3로 lexical 대체: '보안'→포병❌→정보보호병✅, 지문캐시) ② **민원 유형 자동분류 집계**(`/api/complaints-stats`, 자동거부율 추정) ③ **B2G 질병청 오버레이**(KNHANES BMI≥25 참고치+출처/주의, 연도 명시) + Codex 통과(캐시 정합성·BMI 기준 혼선·원자쓰기)
- [x] **Phase 1++** 공공데이터 실연동 확장 — 기획서 주장을 코드로 실현: **모집병 접수현황(15031295)** 특기별 경쟁률·**사회복무 복무기관/소집계획/공석(3066757·53·54)** 지방청 집계·**진로설계센터(15148370)** 지방청 센터 → 로드맵에 실데이터. **실사용 7종**(감염병 15139178=상업금지·신장분포 15117367=3064321 중복은 정직 제외) + Codex 통과(경쟁률 오배정→모집단위 분리·공석 caveat·기준일 노출)
- [ ] Phase 2  데모 시나리오 고정·발표

## AI30 측정 결과 (정직)
intent 거부게이트·민원분류기를 **독립 생성·검증 골드셋**으로 측정. `python scripts/run_eval.py`.
| | 거부게이트 | 민원분류 |
|---|---|---|
| **dev**(튜닝 사용) | P=1.0 R=1.0 [95%CI .91~1.0] F1=1.0 (사유 macro-F1 0.98) | acc 0.98 / macro-F1 0.98 |
| **held-out**(미사용) | R=**0.8** [95%CI .49~.94] P=0.889 F1=0.842 (refuse n=10, fn 2·과잉거부 1) | macro-F1 **0.807** |
> 거부=intent_gate 단독 성능. held-out 위험질문 재현율 0.8(dev 1.0)로 일반화 갭을 정직 노출, **소표본이라 Wilson 95%CI 병기**. 놓친 2건(등급분류·자가진단 요구)도 공개. held-out은 튜닝에 쓰지 않아 측정 무결성 유지 — '측정·검증한 AI'.

### End-to-end RAG (Phase 1, 실 bge-m3 + Qwen3-1.7B) — `python scripts/run_rag_eval.py`
전체 파이프라인(검색→생성→근거율·자기일관성 게이트)을 22문항으로 측정:
| 대상 | 결과 |
|---|---|
| 위험·무관 질문 거부(n=8) | **거부율 1.0** (개인판정·의료·예측·무관 전부 차단) |
| 절차 질문 답변(n=14) | 답변율 **0.857**, 평균 근거율 **0.897** |
| 전체 정확도 | **0.909** |
> 미답변 2건은 자기일관성 게이트가 보수적으로 거부(LLM 3샘플 표현 분기) — 안전 우선의 정직성 비용. **위험질문 거부율 1.0**이 핵심. 원본 수치는 [`eval/rag_e2e_report.json`](eval/rag_e2e_report.json)·요약은 [`eval/RESULTS.md`](eval/RESULTS.md)에 커밋됨(심사위원이 안 돌려도 확인).

## 코드 품질
개발 중 **Codex 코드 리뷰**를 루프로 운영(작성→리뷰→수정→재리뷰→clear). 잡아낸 실이슈:
- Phase 0-1: gap 백분위 버그(치명)·입력검증·serviceKey redaction
- Phase 0-2: 거부 게이트가 위험 표현 다수 누락(치명, 한국어 `\b` 문제)·lexical 게이트 우회
- Phase 0-3: 등급요건 무시 거짓 자격충족(중대)·majors 절단 관련도 왜곡·검증불가를 충족으로 승격·점수내장 자격명 미매칭
- Phase 0-4: 평가가 intent_gate만 측정(end-to-end 아님 명시)·튜닝 패턴의 신규 FP(절차질문 오거부)를 held-out으로 적발·수정
- Phase 0-5: 특기 인덱스 lazy 전처리 동시성 레이스(중대, KeyError)→lock 내 전처리·publish 순서 수정·프런트 escaping 일관화·lifespan 전환(동시 20요청 200 검증)
- Phase 0-6: build_roadmap dict 키 직접 인덱싱 KeyError(중대)→.get 폴백·unknown 특기를 'ok 1순위'로 오표기(중대, 정직성)→warn 분리·프런트 URL 스킴 검증(safeUrl)·fetch 에러처리·키보드 접근성
- Phase 1: bge-llm 폴백 구멍(중대, LLM/reranker가 lazy라 팩토리 except 밖에서 실패)→eager load로 mock 폴백 보장·LLM device/dtype 로드 전 결정(CPU fp32)(중대)·test 모델 로드 pytest 수집 가드(중대)·pad_token/B2G 빈행 방어
- Phase 1+: 특기 임베딩 캐시가 키만 검증(중대, 내용·모델 바뀌면 stale)→지문(내용+모델+dim) 검증·B2G에서 과체중+/비만 명칭이 KNHANES BMI≥25와 혼선(중대)→BMI≥25/≥30 기준 고정·캐시 원자쓰기(os.replace)·allow_pickle=False·min_relevance config화

## 데이터 (실사용 7종 — 코드 검증 / 정직 제외 2종)
실제 호출·사용하는 데이터만 '실사용'으로 표기한다. 각 데이터 수집·집계는 `scripts/fetch_*.py`로 재현.

| 용도 | data.go.kr ID | 실연동 |
|---|---|---|
| 신검 정보(키·체중·BMI, 96,360명 준-전수) | 3064321 | ✅ 백분위·14지방청 히트맵 |
| 모집병 특기 매칭 | 3066750 | ✅ 494특기 인덱스 |
| 모집병 접수현황(경쟁률) | 15031295 | ✅ 특기별 경쟁률(참고·모호 미표시) |
| 사회복무 복무기관 | 3066757 | ✅ 22,028건→지방청 인덱스 |
| 사회복무 소집계획 | 3066753 | ✅ 21,100건→분야 집계 |
| 사회복무 본인선택 공석 | 3066754 | ✅ 216,799건→지방청 집계 |
| 병역진로설계센터 위치 | 15148370 | ✅ 11센터→지방청(fileData CSV) |
| ~~신장 분포(15117367)~~ | 15117367 | ⛔ 제외 — 3064321 준-전수로 상위 대체(중복) |
| ~~감염병(15139178)~~ | 15139178 | ⛔ 제외 — 라이선스 제4유형(상업이용금지) |

**출처·이용조건**: 위 데이터는 **공공데이터포털(data.go.kr)**에서 **공공누리(KOGL)** 조건에 따라
이용하며, 출처는 "**병무청, 공공데이터포털**"로 표시한다(각 데이터셋 상세 유형은 data.go.kr 페이지 기준).
상업이용금지(제4유형)인 감염병(15139178)은 사업화(SaaS) 충돌로 제외했다. 코드 라이선스는 [`LICENSE`](LICENSE) 참조.

실데이터 재수집·재빌드에는 `MMA_SERVICE_KEY`(data.go.kr 서비스키, gitignore된 `.env`)가 필요하다.
단, **데모 실행은 저장소에 포함된 프리빌드 인덱스로 키 없이 동작**한다(위 '바로 실행'). 키가 없을 땐
`data/fixtures`의 합성 데이터로도 엔진을 검증할 수 있다.
