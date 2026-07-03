"""백분위 엔진 데모 — 정직성(범위 밖 거부)이 실제 동작함을 보여준다.

실행:  python scripts/demo_percentile.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.dataio import load_distributions_csv

ROOT = os.path.join(os.path.dirname(__file__), "..")
REAL = os.path.join(ROOT, "data", "distributions_real.csv")
FIXTURE = os.path.join(ROOT, "data", "fixtures", "distributions_sample.csv")


def main():
    # 실데이터(distributions_real.csv) 있으면 우선, 없으면 합성 픽스처
    if os.path.exists(REAL):
        tables = load_distributions_csv(REAL)
        cohort = "2026_전국"
        print("[실데이터: 병무청 3064321, 2026 검사 / 96,360명]\n")
    else:
        tables = load_distributions_csv(FIXTURE)
        cohort = "2024_전국"
        print("[합성 픽스처 — 실 API 키 필요]\n")
    bmi = tables[("bmi", cohort)]
    height = tables[("height", cohort)]

    print(f"=== BMI 백분위 ({cohort}) ===")
    for v in (20.0, 23.0, 27.0, 17.0, 38.0):   # 17·38은 절단 범위 밖
        r = bmi.percentile(v)
        tag = "OK " if r.ok else "거부"
        print(f"[{tag}] BMI {v:>4}  →  {r.as_message('BMI')}")

    print(f"\n=== 신장 백분위 ({cohort}) ===")
    for v in (170.0, 178.0, 152.0):
        r = height.percentile(v)
        tag = "OK " if r.ok else "거부"
        print(f"[{tag}] 신장 {v:>5}cm  →  {r.as_message('신장', unit='cm')}")

    print("\n핵심: 숫자는 파이썬 결정론 계산(환각 불가), 범위 밖은 지어내지 않고 '거부'.")


if __name__ == "__main__":
    main()
