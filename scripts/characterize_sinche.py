"""신체검사 API(3064321) 실데이터 특성화.

전체에서 여러 페이지를 표본으로 받아 분포·범위·코호트 구조를 파악한다.
(절단 여부, 지방청 수, 연도·출생년도 범위, BMI/신장/체중 통계)

실행(네트워크, sandbox off):  python scripts/characterize_sinche.py
"""
import os
import statistics
import sys
from collections import Counter

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))


def _load_env():
    if os.environ.get("MMA_SERVICE_KEY"):
        return
    p = os.path.join(ROOT, ".env")
    if os.path.exists(p):
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    _load_env()
    from mma_navi.mma_api import call_raw, parse_items, SINCHE_GETLIST, ApiError

    # 전체(약 96,360) 위에 흩어진 페이지를 표본 → 코호트 다양성 확인
    pages = [1, 20, 48, 75, 96]
    rows = 1000
    records = []
    for pg in pages:
        try:
            xml = call_raw(SINCHE_GETLIST, pageNo=pg, numOfRows=rows)
            items = parse_items(xml)
            records.extend(items)
            print(f"page {pg}: {len(items)}건")
        except ApiError as e:
            print(f"page {pg}: 실패 {e}")
    print(f"\n총 표본 {len(records)}건\n")
    if not records:
        return 1

    def nums(field):
        out = []
        for r in records:
            try:
                out.append(float(r[field]))
            except (KeyError, ValueError):
                pass
        return out

    bmi = nums("bmi"); height = nums("height"); weight = nums("weight")

    def stat(name, xs, unit=""):
        if not xs:
            print(f"{name}: 없음"); return
        print(f"{name}: n={len(xs)} min={min(xs):.1f} max={max(xs):.1f} "
              f"mean={statistics.mean(xs):.1f} median={statistics.median(xs):.1f}{unit}")

    stat("BMI", bmi); stat("신장", height, "cm"); stat("체중", weight, "kg")

    # 절단 검증: BMI<18.5 / >35 존재?
    if bmi:
        lo = sum(1 for b in bmi if b < 18.5)
        hi = sum(1 for b in bmi if b > 35)
        print(f"\n[절단 검증] BMI<18.5: {lo}건 / BMI>35: {hi}건  "
              f"(0이면 꼬리 제외=population 절단, >0이면 꼬리 존재)")

    print("\n[지방청 jbceong]", dict(Counter(r.get("jbceong", "?") for r in records)))
    print("[검사년도 geomsaDt]", dict(Counter(r.get("geomsaDt", "?") for r in records)))
    print("[출생년도 birth]", dict(sorted(Counter(r.get("birth", "?") for r in records).items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
