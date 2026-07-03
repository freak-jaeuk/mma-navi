"""End-to-end RAG 평가 — intent_gate만이 아니라 전체 파이프라인(검색→생성→게이트) 측정.

run_eval.py(=intent_gate 단독)와 달리, 실제 service.consult()를 통과시켜
검색 근거·생성·근거율·자기일관성까지 반영된 '답하거나 거부'를 평가한다.

평가셋 eval/rag_e2e.json: {text, expected: answer|refuse, (topic|reason)}.
지표:
  - 답변 대상(answer): 답변율(answered), 평균 근거율(grounding)
  - 거부 대상(refuse): 거부율(=정확히 막았는지)
  - 전체 정확도(expected와 일치)

백엔드는 환경변수로:  MMA_RAG=bge-llm MMA_EMBED_DEVICE=cpu MMA_LLM_DEVICE=cuda:0
실행:  python scripts/run_rag_eval.py [--no-write]
"""
import json
import os
import sys
import time

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from mma_navi.app import service  # noqa: E402

EVAL = os.path.join(ROOT, "eval", "rag_e2e.json")


def main():
    items = json.load(open(EVAL, encoding="utf-8"))
    service._get_rag()  # 모델 로드(시간 포함 안 함)
    backend = service._rag_backend
    print(f"=== End-to-end RAG 평가 (backend={backend}, n={len(items)}) ===\n")

    ans_items = [it for it in items if it["expected"] == "answer"]
    ref_items = [it for it in items if it["expected"] == "refuse"]

    answered, groundings, ans_err = 0, [], []
    t0 = time.time()
    for it in ans_items:
        r = service.consult(it["text"])
        if r.get("answered"):
            answered += 1
            if r.get("grounding") is not None:
                groundings.append(r["grounding"])
        else:
            ans_err.append((it["text"], r.get("refusal_reason")))

    refused, ref_err = 0, []
    for it in ref_items:
        r = service.consult(it["text"])
        if not r.get("answered"):
            refused += 1
        else:
            ref_err.append(it["text"])
    dt = time.time() - t0

    n_ans, n_ref = len(ans_items), len(ref_items)
    answer_rate = round(answered / n_ans, 3) if n_ans else None
    refuse_rate = round(refused / n_ref, 3) if n_ref else None
    avg_g = round(sum(groundings) / len(groundings), 3) if groundings else None
    acc = round((answered + refused) / len(items), 3)

    print(f"[답변 대상 n={n_ans}] 답변율={answer_rate}  평균 근거율={avg_g}")
    if ans_err:
        print("  미답변(거부):")
        for t, why in ans_err:
            print(f"    - {t}  ({why})")
    print(f"[거부 대상 n={n_ref}] 거부율={refuse_rate}")
    if ref_err:
        print("  거부 실패(답해버림):")
        for t in ref_err:
            print(f"    - {t}")
    print(f"\n전체 정확도(expected 일치)={acc}  ·  소요 {dt:.1f}s ({dt/len(items):.2f}s/문항)")

    report = {"backend": backend, "n": len(items),
              "answer": {"n": n_ans, "answer_rate": answer_rate, "avg_grounding": avg_g,
                         "errors": ans_err},
              "refuse": {"n": n_ref, "refuse_rate": refuse_rate, "errors": ref_err},
              "accuracy": acc, "seconds": round(dt, 1)}
    if "--no-write" not in sys.argv:
        out = os.path.join(ROOT, "eval", "rag_e2e_report.json")
        json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"리포트 저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
