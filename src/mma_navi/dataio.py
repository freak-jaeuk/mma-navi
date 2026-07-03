"""분포 데이터 로딩.

두 경로를 지원한다:
1) load_distribution_csv  — 로컬 CSV(픽스처 또는 API에서 받아 캐시한 것)에서 로딩.
2) fetch_distribution_api — data.go.kr 오픈API 직접 호출(서비스키 필요).

지금 단계(오프라인 빌드)는 (1)로 엔진을 검증하고, 실제 키가 생기면 (2)로
받아 CSV로 캐시 → 동일 엔진이 그대로 동작한다.

검증된 데이터셋(기능명세서 §6):
- BMI/신장/체중  : data.go.kr 3064321 (신검 정보, BMI 18.5~35 절단)
- 신장 14지방청  : data.go.kr 15117367 (연간 CSV)
"""
from __future__ import annotations

import csv
import math
import os
from typing import Dict, List

from .percentile import Bin, DistributionTable

# CSV 스키마: metric,cohort,bin_low,bin_high,count
_REQUIRED_COLS = {"metric", "cohort", "bin_low", "bin_high", "count"}


def load_distributions_csv(path: str) -> Dict[tuple, DistributionTable]:
    """CSV에서 (metric, cohort) -> DistributionTable 딕셔너리를 만든다."""
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = _REQUIRED_COLS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"CSV 컬럼 누락: {missing} (필요: {_REQUIRED_COLS})")
        grouped: Dict[tuple, List[Bin]] = {}
        for row in reader:
            key = (row["metric"].strip(), row["cohort"].strip())
            grouped.setdefault(key, []).append(
                Bin(
                    low=float(row["bin_low"]),
                    high=float(row["bin_high"]),
                    count=int(float(row["count"])),
                )
            )
    return {
        (metric, cohort): DistributionTable(metric, cohort, bins)
        for (metric, cohort), bins in grouped.items()
    }


def build_table_from_values(metric: str, cohort: str,
                            values, bin_edges) -> DistributionTable:
    """개인 단위 측정값 리스트(microdata)를 히스토그램 DistributionTable로 변환.

    API가 개인 신장·체중을 주면, BMI를 직접 계산한 값 리스트로 분포를 만들 수 있다
    (= 우리가 직접 binning → 절단 우회 가능). 마지막 bin은 상한 포함.
    """
    edges = [float(e) for e in bin_edges]
    if len(edges) < 2:
        raise ValueError("bin_edges는 최소 2개 이상")
    for a, b in zip(edges, edges[1:]):
        if not (math.isfinite(a) and math.isfinite(b)):
            raise ValueError(f"bin_edges에 비유한수 포함: {a}, {b}")
        if not a < b:
            raise ValueError(f"bin_edges는 순증가해야 함(중복/역순 불가): {a} !< {b}")
    vals = list(values)
    bins: List[Bin] = []
    n = len(edges) - 1
    for i, (lo, hi) in enumerate(zip(edges, edges[1:])):
        is_last = (i == n - 1)
        if is_last:
            c = sum(1 for v in vals if lo <= v <= hi)
        else:
            c = sum(1 for v in vals if lo <= v < hi)
        bins.append(Bin(float(lo), float(hi), c))

    # 앞뒤의 빈(0건) bin을 잘라 covered_range가 실제 데이터 범위를 반영하게 한다.
    # (안 그러면 데이터 없는 구간이 '거부'가 아니라 rank 0/100으로 잘못 나옴)
    trimmed = _trim_empty_edges(bins)
    return DistributionTable(metric, cohort, trimmed if trimmed else bins)


def _trim_empty_edges(bins: List[Bin]) -> List[Bin]:
    lo = 0
    hi = len(bins)
    while lo < hi and bins[lo].count == 0:
        lo += 1
    while hi > lo and bins[hi - 1].count == 0:
        hi -= 1
    return bins[lo:hi]


def fetch_distribution_api(metric: str, cohort: str, service_key: str | None = None):
    """data.go.kr 오픈API에서 분포를 받아온다.

    아직 미구현(서비스키 필요). 키가 생기면 여기서 3064321/15117367을 호출하고
    응답을 Bin 리스트로 파싱해 DistributionTable로 반환한다. 그때까지는 CSV 경로 사용.
    """
    key = service_key or os.environ.get("MMA_SERVICE_KEY")
    if not key:
        raise NotImplementedError(
            "실제 API 호출은 MMA_SERVICE_KEY가 필요합니다. "
            "현재는 load_distributions_csv(픽스처)로 엔진을 검증하세요. "
            "키 확보 후 data.go.kr 3064321/15117367 파서를 이 함수에 구현합니다."
        )
    raise NotImplementedError("API 파서 미구현 — 키는 있으나 엔드포인트 파싱 TODO")
