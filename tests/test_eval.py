"""분류기 + 메트릭 테스트 (평가셋 없이 단위 검증).

실행:  python tests/test_eval.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.classify import CATEGORIES, classify  # noqa: E402
from mma_navi.eval import binary_prf, classification_report, wilson_ci  # noqa: E402


def test_classify_basic():
    cases = {
        "신검 절차 알려줘": "신검",
        "모집병 특기 추천해줘": "모집병",
        "사회복무 복무기관 어디서 조회해?": "사회복무",
        "여비 교통비 어떻게 신청해?": "여비",
        "진로설계센터 상담 예약하고 싶어": "진로",
    }
    for q, exp in cases.items():
        got, _ = classify(q)
        assert got == exp, f"{q} → {got} (기대 {exp})"


def test_classify_unknown():
    got, _ = classify("오늘 점심 뭐 먹지")
    assert got == "미상"


def test_binary_prf_known():
    yt = ["refuse", "refuse", "answer", "answer"]
    yp = ["refuse", "answer", "answer", "refuse"]
    r = binary_prf(yt, yp, "refuse")
    assert r["tp"] == 1 and r["fp"] == 1 and r["fn"] == 1
    assert r["precision"] == 0.5 and r["recall"] == 0.5 and r["f1"] == 0.5


def test_binary_prf_perfect():
    yt = ["refuse", "answer", "refuse"]
    r = binary_prf(yt, yt, "refuse")
    assert r["precision"] == 1.0 and r["recall"] == 1.0 and r["f1"] == 1.0


def test_classification_report():
    yt = ["신검", "모집병", "사회복무", "신검"]
    yp = ["신검", "모집병", "여비", "신검"]
    rep = classification_report(yt, yp, CATEGORIES)
    assert rep["accuracy"] == 0.75
    assert 0.0 <= rep["macro_f1"] <= 1.0
    assert rep["per_class"]["신검"]["f1"] == 1.0


def test_prf_length_mismatch_raises():
    try:
        binary_prf([1, 2], [1], 1)
    except ValueError:
        return
    raise AssertionError("길이 불일치 미검출")


def test_wilson_ci_bounds_and_empty():
    assert wilson_ci(0, 0) is None            # 표본 없음 → 구간 없음
    lo, hi = wilson_ci(10, 10)                # 완전 성공: 상한 1.0, 하한<1
    assert hi == 1.0 and 0.0 <= lo < 1.0
    lo2, hi2 = wilson_ci(8, 10)               # 0.8 점추정을 구간이 포함
    assert lo2 <= 0.8 <= hi2 and 0.0 <= lo2 < hi2 <= 1.0
    for bad in [(-1, 10), (11, 10)]:          # k<0, k>n → 명시적 실패
        try:
            wilson_ci(*bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"잘못된 입력 미검출: {bad}")


def test_binary_prf_includes_recall_ci():
    r = binary_prf(["refuse", "refuse", "answer"], ["refuse", "answer", "answer"], "refuse")
    assert r["recall"] == 0.5 and r["recall_ci"] is not None      # tp+fn=2 → 구간 존재
    assert r["recall_ci"][0] <= 0.5 <= r["recall_ci"][1]
    empty = binary_prf(["answer"], ["answer"], "refuse")
    assert empty["recall_ci"] is None                              # positive 없음 → None


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"  ok    {fn.__name__}")
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
