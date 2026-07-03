"""백분위 엔진 자체 테스트 (pytest 없이 표준 assert로 실행).

실행:  python tests/test_percentile.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.percentile import (  # noqa: E402
    AbstainReason,
    Bin,
    DistributionTable,
)
from mma_navi.dataio import load_distributions_csv, build_table_from_values  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures",
                       "distributions_sample.csv")


def _controlled():
    # [0,10):100, [10,20):100  → 총 200, 균등 두 칸
    return DistributionTable("x", "test", [Bin(0, 10, 100), Bin(10, 20, 100)])


def test_exact_values():
    t = _controlled()
    assert t.percentile(0).percentile_rank == 0.0
    assert t.percentile(5).percentile_rank == 25.0
    assert t.percentile(10).percentile_rank == 50.0
    assert t.percentile(15).percentile_rank == 75.0
    assert t.percentile(20).percentile_rank == 100.0


def test_top_percent_complement():
    t = _controlled()
    for v in (1, 7, 12, 18):
        r = t.percentile(v)
        assert r.ok
        assert r.top_percent == round(100.0 - r.percentile_rank, 1)


def test_abstain_below_above():
    t = _controlled()
    below = t.percentile(-1)
    assert not below.ok and below.abstain_reason == AbstainReason.BELOW_MIN
    above = t.percentile(21)
    assert not above.ok and above.abstain_reason == AbstainReason.ABOVE_MAX
    # 커버 범위가 메시지에 정직히 노출되는지
    assert below.covered_range == (0, 20)


def test_no_data():
    # count 0짜리 분포
    t = DistributionTable("x", "empty", [Bin(0, 10, 0)])
    r = t.percentile(5)
    assert not r.ok and r.abstain_reason == AbstainReason.NO_DATA


def test_determinism():
    t1 = _controlled()
    t2 = _controlled()
    for v in (3.3, 9.99, 10.0, 14.7):
        a = t1.percentile(v)
        b = t2.percentile(v)
        assert a == b  # frozen dataclass 동등성 = 완전 재현


def test_monotonic_on_fixture():
    tables = load_distributions_csv(FIXTURE)
    bmi = tables[("bmi", "2024_전국")]
    r20 = bmi.percentile(20.0).percentile_rank
    r23 = bmi.percentile(23.0).percentile_rank
    r24 = bmi.percentile(24.0).percentile_rank
    assert r20 < r23 < r24  # 값이 클수록 백분위도 큼


def test_fixture_known_value():
    tables = load_distributions_csv(FIXTURE)
    bmi = tables[("bmi", "2024_전국")]
    r = bmi.percentile(23.0)
    # 23 미만 누적 108,000 / 총 300,000 = 36.0
    assert r.ok
    assert r.percentile_rank == 36.0
    assert r.top_percent == 64.0
    assert r.cohort_size == 300000


def test_fixture_cohorts_present():
    tables = load_distributions_csv(FIXTURE)
    assert ("bmi", "2024_전국") in tables
    assert ("height", "2024_전국") in tables
    assert ("height", "2024_서울") in tables  # 지방청 코호트 분리 확인


def test_bmi_truncation_abstains():
    # 공개 API 절단(18.5~35) 밖 = 저체중/고도비만 꼬리는 거부해야 정직
    tables = load_distributions_csv(FIXTURE)
    bmi = tables[("bmi", "2024_전국")]
    assert bmi.percentile(17.0).abstain_reason == AbstainReason.BELOW_MIN
    assert bmi.percentile(38.0).abstain_reason == AbstainReason.ABOVE_MAX


def test_messages():
    tables = load_distributions_csv(FIXTURE)
    bmi = tables[("bmi", "2024_전국")]
    ok_msg = bmi.percentile(23.0).as_message("BMI")
    assert "백분위" in ok_msg and "또래" in ok_msg and "신체등급 예측이 아닙니다" in ok_msg
    ab_msg = bmi.percentile(40.0).as_message("BMI")
    assert "범위" in ab_msg


def test_gap_abstains():
    # (Codex 치명) bin 사이 gap → 그 사이 값은 NO_COVERAGE 거부, 잘못된 백분위 금지
    t = DistributionTable("x", "gap", [Bin(0, 10, 100), Bin(20, 30, 100)])
    r = t.percentile(15)
    assert not r.ok and r.abstain_reason == AbstainReason.NO_COVERAGE


def test_interior_zero_bin_is_flat():
    # 연속 bin의 0-count 내부 구간 = 유효한 0확률 구간(평탄 CDF), 거부 아님(정책 고정)
    t = DistributionTable("x", "z", [Bin(0, 10, 50), Bin(10, 20, 0), Bin(20, 30, 50)])
    r = t.percentile(15)
    assert r.ok and r.percentile_rank == 50.0


def test_nan_inf_abstain():
    t = _controlled()
    for bad in (float("nan"), float("inf"), float("-inf")):
        r = t.percentile(bad)
        assert not r.ok and r.abstain_reason == AbstainReason.INVALID_INPUT


def test_bad_bin_rejected():
    for args in [(10, 0, 5), (0, 0, 5), (0, 10, -1)]:
        try:
            Bin(*args)
        except ValueError:
            continue
        raise AssertionError(f"불량 bin이 거부되지 않음: {args}")


def test_bad_edges_rejected():
    for edges in ([5, 1, 9], [0, 0, 10], [0, float("nan")]):
        try:
            build_table_from_values("x", "c", [1, 2, 3], edges)
        except ValueError:
            continue
        raise AssertionError(f"불량 edges가 거부되지 않음: {edges}")


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
