# AI 성능·안전성 측정 결과 (AI30 증거)

> "측정·검증한 AI." 아래 수치는 저장소에 **파일로 커밋**되어 있어, 심사위원이 직접 돌리지
> 않아도 확인 가능하다. 골드셋은 독립 생성·검증했고, **학습에 쓰지 않은 held-out(미사용)**
> 셋으로 일반화 성능까지 정직하게 공개한다.

## 1. 거부 게이트 · 민원 분류 — 키·GPU 없이 재현 가능

원본: [`report.json`](report.json) · 실행 로그: [`run_eval_output.txt`](run_eval_output.txt)
재현: `python scripts/run_eval.py --out eval/report.json` (인증키·GPU 불필요)

| 구분 | 과제 | n | 지표 |
|---|---|---|---|
| 개발셋(dev) | 위험질문 자동거부 | 66 (거부 38) | 정밀도 1.0 / 재현율 1.0 [95%CI 0.908~1.0] / F1 1.0 |
| 개발셋(dev) | 거부 사유 분류 | 66 | 사유분류 F1 0.981 |
| 개발셋(dev) | 민원 5범주 분류 | 50 | 정확도 0.98 / 평균 F1 0.98 |
| **미사용셋(held-out)** | 위험질문 자동거부 | 22 (거부 10) | 정밀도 0.889 / 재현율 0.8 [95%CI 0.49~0.94] / F1 0.842 |
| **미사용셋(held-out)** | 거부 사유 분류 | 22 | 사유분류 F1 0.857 |
| **미사용셋(held-out)** | 민원 5범주 분류 | 20 | 정확도 0.8 / 평균 F1 0.807 |

- 거부 성능은 **질문의도 자동판별 단독** 측정(실제 상담 답변 연결은 아래 2).
- held-out에서 fp 1(과잉거부), fn 2(놓친 위험질문) — 게이트를 held-out에 맞춰 튜닝하지 않고
  **일반화 갭을 그대로 노출**한다(수치 부풀리기 방지).

## 2. 상담 파이프라인 end-to-end — 헤드라인 (bge-llm, GPU 필요)

원본: [`rag_e2e_report.json`](rag_e2e_report.json) · 백엔드 `bge-llm`(bge-m3 검색 + 로컬 Qwen 생성)

| 지표 | 값 |
|---|---|
| 문항 수 | 22 (답변 14 / 거부 8) |
| **종합 정확도** | **0.909** |
| 답변 문항 정답률 | 0.857 |
| 평균 근거 충실도(grounding) | 0.897 |
| 위험질문 거부율 | 1.0 (8/8) |
| 소요 | 23.6s |

> 이 표는 GPU + 로컬 Qwen이 필요해 심사위원이 직접 재현하긴 어렵다. 그래서 실행 결과를
> JSON으로 커밋해 두었다. 라이브 데모(무료·GPU無)는 `bge-extractive`/`mock` 모드로,
> 백분위·특기(의미랭킹)·로드맵·거부 게이트의 **작동 자체**를 확인할 수 있다(배포: `deploy/`).

## 골드셋 파일
- 개발셋: [`refusal_set.json`](refusal_set.json) · [`classify_set.json`](classify_set.json)
- 미사용셋: [`refusal_test.json`](refusal_test.json) · [`classify_test.json`](classify_test.json)
- end-to-end 문항: [`rag_e2e.json`](rag_e2e.json)
