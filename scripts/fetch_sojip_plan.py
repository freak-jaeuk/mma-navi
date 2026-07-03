"""사회복무 연도별 소집계획(3066753) 전량 수집 → 복무분야별 계획인원 집계.

지역 필드가 없어 전국 분야별 집계다. 산출 data/sojip_plan.json =
{_meta:{year,total_pcnt,agency_count}, fields:[{name,pcnt,agencies}, ...]} (인원순).
담당자(B2G) 화면의 '올해 사회복무 소집 계획' 인사이트에 쓴다.

실행: MMA_SERVICE_KEY 필요.  python scripts/fetch_sojip_plan.py
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from mma_navi.mma_api import call_raw, parse_items  # noqa: E402

ENDPOINT = "https://apis.data.go.kr/1300000/sHBMGyeHeok/list"
OUT = os.path.join(ROOT, "data", "sojip_plan.json")
ROWS = 1000


def _total(xml: str) -> int:
    m = re.search(r"<totalCount>(\d+)</totalCount>", xml or "")
    return int(m.group(1)) if m else 0


def main() -> int:
    if not os.environ.get("MMA_SERVICE_KEY"):
        print("MMA_SERVICE_KEY 없음")
        return 1
    fields: dict = {}          # 분야명 → {"pcnt": int, "agencies": int}
    years: dict = {}
    page, total, got = 1, None, 0
    while True:
        xml = call_raw(ENDPOINT, pageNo=page, numOfRows=ROWS)
        if total is None:
            total = _total(xml)
            print(f"총 {total}건")
        items = parse_items(xml)
        if not items:
            break
        for it in items:
            name = (it.get("bmbunyaNm") or "").strip() or "미상"
            try:
                pcnt = int(it.get("jhgyehoekPcnt") or 0)
            except ValueError:
                pcnt = 0
            years[it.get("shbmsojipDt", "")] = years.get(it.get("shbmsojipDt", ""), 0) + 1
            f = fields.setdefault(name, {"pcnt": 0, "agencies": 0})
            f["pcnt"] += pcnt
            f["agencies"] += 1
        got += len(items)
        print(f"  page {page}: +{len(items)} ({got}/{total})")
        if got >= (total or 0) or len(items) < ROWS:
            break
        page += 1

    ranked = sorted(({"name": k, "pcnt": v["pcnt"], "agencies": v["agencies"]}
                     for k, v in fields.items()), key=lambda x: -x["pcnt"])
    year = max(years, key=years.get) if years else ""
    payload = {"_meta": {"year": year, "total_pcnt": sum(f["pcnt"] for f in ranked),
                         "agency_count": got, "field_count": len(ranked),
                         "source": "병무청 사회복무 연도별 소집계획 API(3066753)"},
               "fields": ranked}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"\n저장: {OUT}  ({len(ranked)}개 분야, 총 계획인원 {payload['_meta']['total_pcnt']})")
    print("상위:", [(r["name"], r["pcnt"]) for r in ranked[:5]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
