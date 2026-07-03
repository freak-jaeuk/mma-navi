"""병역진로설계지원센터 위치(15148370) CSV → 지방청별 센터 인덱스.

data.go.kr 파일데이터(cp949 CSV, 11행)를 파싱해 관할지방청별로 묶는다.
산출 data/jinro_centers.json = {regions:{지방청: [{name,addr,tel,note}]}}.
로드맵 5단계(진로설계센터 상담)에서 사용자 지방청의 실제 센터를 안내한다.

실행: python scripts/build_jinro_centers.py  (사전에 CSV를 data/에 저장)
"""
import csv
import glob
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
DATA = os.path.join(ROOT, "data")
OUT = os.path.join(DATA, "jinro_centers.json")


def _find_csv() -> str:
    for pat in ("*진로설계*센터*.csv", "*진로설계*.csv", "jinro_centers.csv"):
        hits = glob.glob(os.path.join(DATA, pat))
        if hits:
            return sorted(hits)[-1]      # 파일명 날짜(YYYYMMDD) 기준 최신 선택
    return ""


def _date_from(name: str) -> str:
    m = re.search(r"(\d{4})(\d{2})(\d{2})", name)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def main() -> int:
    src = _find_csv()
    if not src:
        print("진로설계센터 CSV를 data/에서 찾지 못함")
        return 1
    with open(src, encoding="cp949") as f:            # data.go.kr 파일데이터 = cp949
        rows = list(csv.DictReader(f))

    regions: dict = {}
    for row in rows:
        r = {(k or "").strip(): (v or "").strip() for k, v in row.items()}
        region = r.get("관할지방청명", "")
        name = r.get("병역진로센터 명", "")
        if not region or not name:
            continue
        addr = " ".join(x for x in (r.get("기본 주소", ""), r.get("상세 주소", "")) if x)
        regions.setdefault(region, []).append({
            "name": name, "addr": addr,
            "tel": r.get("대표전화번호", ""), "note": r.get("위치참고내용", ""),
        })

    payload = {"_meta": {"centers": sum(len(v) for v in regions.values()),
                         "region_count": len(regions),
                         "data_date": _date_from(os.path.basename(src)),
                         "source": "병무청 병역진로설계지원센터 위치(15148370)"},
               "regions": regions}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"저장: {OUT}  ({payload['_meta']['centers']}센터, {len(regions)}개 지방청)")
    print("지방청:", {k: [c["name"] for c in v] for k, v in sorted(regions.items())})
    return 0


if __name__ == "__main__":
    sys.exit(main())
