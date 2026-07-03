"""AI30 증거물: intent 거부 게이트·민원 분류기를 골드셋으로 측정 → P/R/F1.

정직성 주의:
- 거부 측정은 **intent_gate(의도 게이트) 단독** 성능이다. 실제 RagPipeline은 검색없음/
  자기일관성/근거율로도 거부하므로, 이 수치는 'RAG end-to-end'가 아니라 '의도 안전게이트'다.
  (end-to-end RAG 평가는 실 KB 연결되는 Phase 1에서.)
- dev(튜닝에 사용)와 held-out(미사용, 일반화 추정)을 분리 측정해 둘 다 보고한다.

평가셋:
  eval/refusal_set.json + eval/classify_set.json     (dev)
  eval/refusal_test.json + eval/classify_test.json   (held-out, 있으면)

실행:  python scripts/run_eval.py [--no-write]
"""
import json
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from mma_navi.classify import CATEGORIES, classify          # noqa: E402
from mma_navi.eval import binary_prf, classification_report  # noqa: E402
from mma_navi.rag.gates import intent_gate                   # noqa: E402

EVAL_DIR = os.path.join(ROOT, "eval")
REFUSE_CATS = ["개인판정", "의료진단", "합격예측"]


def _load(name):
    p = os.path.join(EVAL_DIR, name)
    return json.load(open(p, encoding="utf-8")) if os.path.exists(p) else None


def eval_refusal(items):
    preds = [intent_gate(it["text"]) for it in items]
    y_true_a = [it["expected"] for it in items]
    y_pred_a = ["refuse" if r else "answer" for r in preds]
    has_pos = any(t == "refuse" for t in y_true_a)
    binary = binary_prf(y_true_a, y_pred_a, "refuse")
    binary["answer_only"] = not has_pos
    if not has_pos:   # held-out answer-only → P/R/F1 무의미, 과잉거부만 유효
        binary["precision"] = binary["recall"] = binary["f1"] = None
        binary["answer_accuracy"] = round((len(items) - binary["fp"]) / len(items), 3)
        binary["note"] = "answer-only set: 과잉거부(FP)·answer정확도만 유효"

    labels = REFUSE_CATS + ["answer"]
    y_true_c = [(it["category"] if it["expected"] == "refuse" else "answer") for it in items]
    y_pred_c = [(r.value if r else "answer") for r in preds]
    by_cat = None if not has_pos else classification_report(y_true_c, y_pred_c, labels)

    binary_err = [{"text": it["text"], "true": t, "pred": p}
                  for it, t, p in zip(items, y_true_a, y_pred_a) if t != p]
    cat_err = [{"text": it["text"], "true": t, "pred": p}
               for it, t, p in zip(items, y_true_c, y_pred_c) if t != p]
    return {"intent_gate_refusal": binary, "by_category": by_cat, "n": len(items),
            "binary_errors": binary_err[:20], "category_errors": cat_err[:20]}


def eval_classify(items):
    y_true = [it["category"] for it in items]
    y_pred = [classify(it["text"])[0] for it in items]
    rep = classification_report(y_true, y_pred, CATEGORIES)
    rep["errors"] = [{"text": it["text"], "true": t, "pred": p}
                     for it, t, p in zip(items, y_true, y_pred) if t != p][:20]
    return rep


def _print_block(tag, refusal, classify_rep):
    if refusal:
        b = refusal["intent_gate_refusal"]
        if b.get("answer_only"):
            print(f"[{tag}] 의도 거부게이트 (n={refusal['n']}, answer-only): "
                  f"과잉거부(FP)={b['fp']}/{refusal['n']}  answer정확도={b['answer_accuracy']}")
        else:
            rci = b.get("recall_ci")
            ci = f" [95%CI {rci[0]}~{rci[1]}]" if rci else ""
            print(f"[{tag}] 의도 거부게이트 (n={refusal['n']}, refuse={b['tp'] + b['fn']}): "
                  f"P={b['precision']} R={b['recall']}{ci} F1={b['f1']} fp={b['fp']} fn={b['fn']}")
            print(f"        사유 macro-F1={refusal['by_category']['macro_f1']}")
    if classify_rep:
        print(f"[{tag}] 민원 분류 (n={classify_rep['n']}): "
              f"acc={classify_rep['accuracy']} macro-F1={classify_rep['macro_f1']}"
              + (f" / 미상={classify_rep['unknown_labels']}" if classify_rep['unknown_labels'] else ""))


def main():
    report = {}
    dev_r, dev_c = _load("refusal_set.json"), _load("classify_set.json")
    test_r, test_c = _load("refusal_test.json"), _load("classify_test.json")

    print("=== AI30 메트릭 (intent 게이트 + 분류기) ===")
    print("※ 거부=intent_gate 단독 성능(RAG end-to-end 아님). dev=튜닝사용 / held-out=일반화 추정\n")
    if dev_r or dev_c:
        report["dev"] = {"refusal": eval_refusal(dev_r) if dev_r else None,
                         "classify": eval_classify(dev_c) if dev_c else None}
        _print_block("dev     ", report["dev"]["refusal"], report["dev"]["classify"])
    if test_r or test_c:
        report["holdout"] = {"refusal": eval_refusal(test_r) if test_r else None,
                             "classify": eval_classify(test_c) if test_c else None}
        _print_block("held-out", report["holdout"]["refusal"], report["holdout"]["classify"])

    if "--no-write" not in sys.argv:
        out = os.path.join(EVAL_DIR, "report.json")
        json.dump(report, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print(f"\n리포트 저장: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
