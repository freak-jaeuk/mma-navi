"""결정론적 백분위 엔진 (Deterministic Percentile Engine).

병무청 신체검사 집계 분포(히스토그램)로부터 개인 측정값의 백분위를 **계산**한다.
학습 모델이 아니라 결정론 lookup이므로 환각이 구조적으로 불가능하다 — 같은 입력은
항상 같은 출력을 낸다.

핵심 정직성 규칙(기능명세서 §F3, §4 가드레일):
- 데이터 커버 범위 밖(예: BMI<18.5 또는 >35 — 공개 데이터 모집단 절단)의 값은
  숫자를 지어내지 않고 ABSTAIN('범위 밖')을 반환한다.
- **커버 정책:** 연속된 bin 사이의 0-count 구간은 '유효한 0확률 구간'으로 보고
  평탄한 CDF로 백분위를 준다. 그러나 bin 경계 자체에 gap(b.low > 이전 b.high)이
  있으면 미커버로 보고 ABSTAIN(NO_COVERAGE)한다.
- 이 모듈은 **백분위만** 계산한다. 개인 신체등급/합격/면제 예측은 하지 않는다
  (집계로는 통계적으로 불가능 = 생태학적 오류).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Sequence, Tuple


class AbstainReason(str, Enum):
    """백분위를 계산하지 않고 거부하는 사유."""
    BELOW_MIN = "below_min"       # 데이터 최솟값 미만 (절단된 하한 꼬리)
    ABOVE_MAX = "above_max"       # 데이터 최댓값 초과 (절단된 상한 꼬리)
    NO_COVERAGE = "no_coverage"   # 범위 안이지만 bin gap에 떨어짐 (미커버)
    NO_DATA = "no_data"           # 분포가 비어 있음
    INVALID_INPUT = "invalid_input"  # NaN/inf 등 비정상 입력


@dataclass(frozen=True)
class Bin:
    """히스토그램 한 칸. 구간 [low, high), 마지막 bin만 high 포함."""
    low: float
    high: float
    count: int

    def __post_init__(self):
        if not (math.isfinite(self.low) and math.isfinite(self.high)):
            raise ValueError(f"bin 경계가 유한수가 아님: [{self.low}, {self.high})")
        if self.high <= self.low:
            raise ValueError(f"bin 폭이 0 이하: [{self.low}, {self.high})")
        if self.count < 0:
            raise ValueError(f"bin count 음수: {self.count}")

    @property
    def width(self) -> float:
        return self.high - self.low


@dataclass(frozen=True)
class PercentileResult:
    ok: bool
    percentile_rank: Optional[float] = None   # 0~100, 이 값 이하인 또래 비율
    top_percent: Optional[float] = None        # 100 - percentile_rank
    abstain_reason: Optional[AbstainReason] = None
    covered_range: Optional[Tuple[float, float]] = None
    cohort_size: int = 0

    def as_message(self, metric_label: str, unit: str = "") -> str:
        """사용자 노출용 한국어 메시지(해설 LLM의 입력 '확정 사실')."""
        if self.ok:
            # 가치중립 표현: '상위 X%'는 BMI 등에서 오해 소지 → '낮은/높은 또래 비율'로.
            return (
                f"{metric_label}은(는) 동년 병역판정 대상자 {self.cohort_size:,}명 기준 "
                f"백분위 {self.percentile_rank:g}입니다 "
                f"(나보다 낮은 또래 {self.percentile_rank:g}%, "
                f"높은 또래 {self.top_percent:g}%). "
                f"※ 백분위 정보이며 신체등급 예측이 아닙니다."
            )
        if self.abstain_reason in (AbstainReason.BELOW_MIN, AbstainReason.ABOVE_MAX,
                                   AbstainReason.NO_COVERAGE):
            lo, hi = self.covered_range or (None, None)
            return (
                f"입력값이 공개 데이터 표시 범위({lo:g}~{hi:g}{unit}) 밖이거나 "
                f"집계 구간에 없어 백분위를 제공하지 않습니다. "
                f"(범위 밖은 정직하게 '판단 보류')"
            )
        if self.abstain_reason == AbstainReason.INVALID_INPUT:
            return "입력값이 올바른 숫자가 아니어서 백분위를 계산할 수 없습니다."
        return "분포 데이터가 없어 백분위를 계산할 수 없습니다."


class DistributionTable:
    """한 지표·코호트의 집계 분포(히스토그램)."""

    def __init__(self, metric: str, cohort: str, bins: Sequence[Bin]):
        if not bins:
            raise ValueError("bins가 비어 있습니다")
        self.metric = metric
        self.cohort = cohort
        self.bins = sorted(bins, key=lambda b: b.low)
        self._validate_no_overlap()
        self.total = sum(b.count for b in self.bins)

    def _validate_no_overlap(self) -> None:
        # 겹침은 데이터 오류 → 거부. (gap은 허용하되 percentile에서 NO_COVERAGE 처리)
        for a, b in zip(self.bins, self.bins[1:]):
            if b.low < a.high - 1e-9:
                raise ValueError(f"bin 겹침: [{a.low},{a.high}) vs [{b.low},{b.high})")

    @property
    def vmin(self) -> float:
        return self.bins[0].low

    @property
    def vmax(self) -> float:
        return self.bins[-1].high

    def percentile(self, value: float) -> PercentileResult:
        """value의 백분위를 결정론적으로 계산. 범위 밖/미커버/비정상은 ABSTAIN."""
        rng = (self.vmin, self.vmax)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return PercentileResult(ok=False, abstain_reason=AbstainReason.INVALID_INPUT,
                                    covered_range=rng, cohort_size=self.total)
        if self.total <= 0:
            return PercentileResult(ok=False, abstain_reason=AbstainReason.NO_DATA,
                                    covered_range=rng)
        if value < self.vmin:
            return PercentileResult(ok=False, abstain_reason=AbstainReason.BELOW_MIN,
                                    covered_range=rng, cohort_size=self.total)
        if value > self.vmax:
            return PercentileResult(ok=False, abstain_reason=AbstainReason.ABOVE_MAX,
                                    covered_range=rng, cohort_size=self.total)

        cum = 0
        n = len(self.bins)
        for i, b in enumerate(self.bins):
            if value < b.low:
                # 이전 bin의 high와 이 bin의 low 사이 gap에 떨어짐 = 미커버
                return PercentileResult(ok=False, abstain_reason=AbstainReason.NO_COVERAGE,
                                        covered_range=rng, cohort_size=self.total)
            is_last = (i == n - 1)
            in_bin = (b.low <= value <= b.high) if is_last else (b.low <= value < b.high)
            if in_bin:
                frac = (value - b.low) / b.width if b.width > 0 else 0.0
                frac = min(1.0, max(0.0, frac))            # 경계 보호
                below = cum + frac * b.count                # bin 내 균등 가정
                rank = below / self.total * 100.0
                rank = min(100.0, max(0.0, rank))
                return PercentileResult(
                    ok=True,
                    percentile_rank=round(rank, 1),
                    top_percent=round(100.0 - rank, 1),
                    covered_range=rng,
                    cohort_size=self.total,
                )
            cum += b.count   # value >= b.high → 이 bin 전체가 아래
        # 도달 불가(위 범위 체크로 보장). 방어적 ABSTAIN.
        return PercentileResult(ok=False, abstain_reason=AbstainReason.NO_COVERAGE,
                                covered_range=rng, cohort_size=self.total)
