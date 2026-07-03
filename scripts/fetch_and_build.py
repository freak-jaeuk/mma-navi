"""신체검사 API(3064321) 전체 수집 → 실제 분포(전국 + 14지방청) 빌드.

1) 전 페이지 페이지네이션으로 microdata 수집 → data/cache/ 에 원시 캐시(gitignore)
2) BMI/신장/체중 히스토그램을 전국 + 지방청별로 빌드 → data/distributions_real.csv
   (배포 아티팩트는 집계 분포만 — 개인 microdata는 캐시에만 보관)

실행(네트워크, sandbox off):  python scripts/fetch_and_build.py
"""
import csv
import os
import sys
import xml.etree.ElementTree as ET

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

CACHE_DIR = os.path.join(ROOT, "data", "cache")
OUT_CSV = os.path.join(ROOT, "data", "distributions_real.csv")

# 빈 경계 (관측 범위를 넉넉히 커버)
BMI_EDGES = [18.5 + 0.5 * i for i in range(int((35.0 - 18.5) / 0.5) + 1)]      # 18.5~35.0
HEIGHT_EDGES = list(range(130, 216, 1))                                         # 130~215cm
WEIGHT_EDGES = list(range(30, 171, 2))                                          # 30~170kg


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


def fetch_all(max_pages=200, rows=1000):
    from mma_navi.mma_api import call_raw, parse_items, SINCHE_GETLIST
    records, total = [], None
    for page in range(1, max_pages + 1):
        xml = call_raw(SINCHE_GETLIST, pageNo=page, numOfRows=rows)
        if total is None:
            t = ET.fromstring(xml).findtext(".//totalCount")
            total = int(t) if t else None
        items = parse_items(xml)
        if not items:
            break
        records.extend(items)
        if total and len(records) >= total:
            break
        if page % 10 == 0:
            print(f"  ...{len(records)}/{total}")
    return records, total


def main():
    _load_env()
    from mma_navi.dataio import build_table_from_values

    os.makedirs(CACHE_DIR, exist_ok=True)
    cache = os.path.join(CACHE_DIR, "sinche_microdata.csv")
    fields = ["birth", "geomsaDt", "jbceong", "height", "weight", "bmi",
              "leftSight", "rightSight"]

    use_cache = ("--refetch" not in sys.argv) and os.path.exists(cache)
    if use_cache:
        with open(cache, newline="", encoding="utf-8") as f:
            records = list(csv.DictReader(f))
        print(f"캐시 사용: {cache} ({len(records)}건) — 재빌드만 (API 재호출 안 함, "
              f"새로 받으려면 --refetch)")
    else:
        print("수집 중...")
        records, total = fetch_all()
        print(f"수집 완료: {len(records)}건 (totalCount={total})")
        if not records:
            return 1
        with open(cache, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            w.writeheader()
            w.writerows(records)
        print(f"원시 캐시 저장: {cache}")

    year = records[0].get("geomsaDt", "0000")
    offices = sorted({r.get("jbceong", "?") for r in records})

    def vals(recs, field):
        out = []
        for r in recs:
            try:
                out.append(float(r[field]))
            except (KeyError, ValueError):
                pass
        return out

    metrics = [("bmi", "bmi", BMI_EDGES),
               ("height", "height", HEIGHT_EDGES),
               ("weight", "weight", WEIGHT_EDGES)]

    rows_out = []

    def emit(metric, cohort, table):
        for b in table.bins:
            rows_out.append([metric, cohort, b.low, b.high, b.count])

    # 전국
    for metric, field, edges in metrics:
        t = build_table_from_values(metric, f"{year}_전국", vals(records, field), edges)
        emit(metric, f"{year}_전국", t)
    # 14지방청
    for office in offices:
        sub = [r for r in records if r.get("jbceong") == office]
        for metric, field, edges in metrics:
            t = build_table_from_values(metric, f"{year}_{office}", vals(sub, field), edges)
            emit(metric, f"{year}_{office}", t)

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["metric", "cohort", "bin_low", "bin_high", "count"])
        w.writerows(rows_out)
    print(f"실제 분포 저장: {OUT_CSV}  ({len(rows_out)}행, 코호트 {1 + len(offices)}개)")
    print(f"지방청: {offices}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
