"""사회복무 본인선택 공석(3066754) 전량 수집 → 지방청별 공석 집계.

서버측 지역 필터가 없어(전국 22만여 건) 전량 페이징 후 관할지방청(ghjbcNm)별로
공석배정인원 합계·건수·표본을 집계한다. 산출 data/gongseok_by_region.json =
{regions:{지방청: {baejeong, records, sample:[{gigwan,sigungu,baejeong,tms,type}]}}}.
공석은 실시간 스냅샷이라 재수집 시 값이 바뀐다(예측 아님).

실행: MMA_SERVICE_KEY 필요.  python scripts/fetch_gongseok.py
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from mma_navi.mma_api import call_raw, parse_items  # noqa: E402

ENDPOINT = "https://apis.data.go.kr/1300000/bistGongseok/list/bistGongseok/list"
OUT = os.path.join(ROOT, "data", "gongseok_by_region.json")
ROWS = 1000
SAMPLE = 5


def _total(xml: str) -> int:
    m = re.search(r"<totalCount>(\d+)</totalCount>", xml or "")
    return int(m.group(1)) if m else 0


def _int(s) -> int:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return 0


def main() -> int:
    if not os.environ.get("MMA_SERVICE_KEY"):
        print("MMA_SERVICE_KEY 없음")
        return 1
    regions: dict = {}
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
            region = (it.get("ghjbcNm") or "").strip()
            if not region:
                continue
            r = regions.setdefault(region, {"baejeong": 0, "records": 0, "sample": []})
            baejeong = max(0, _int(it.get("gsbaejeongPcnt")))   # 음수 이상값 방어
            r["baejeong"] += baejeong
            r["records"] += 1
            if len(r["sample"]) < SAMPLE and it.get("bmgigwanNm"):
                r["sample"].append({
                    "gigwan": (it.get("bmgigwanNm") or "").strip(),
                    "sigungu": (it.get("bjdsggjusoNm") or "").strip(),
                    "baejeong": baejeong,
                    "tms": _int(it.get("jeopsuTms")),
                    "type": (it.get("jeopsutypeCd") or "").strip(),
                })
        got += len(items)
        if page % 20 == 0 or (total and got >= total):
            print(f"  {got}/{total}")
        # totalCount를 못 읽으면(None/0) 마지막 부분 페이지(len<ROWS)까지 계속 — 조용한 부분수집 방지
        if (total and got >= total) or len(items) < ROWS:
            break
        page += 1

    payload = {"_meta": {"records": got, "region_count": len(regions),
                         "source": "병무청 사회복무 본인선택 공석 API(3066754)",
                         "caveat": "실시간 스냅샷(재수집 시 변동, 미래 결과 예측 아님)."},
               "regions": regions}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"\n저장: {OUT}  ({len(regions)}개 지방청, {got}건)")
    print("지방청별 배정:", {k: v["baejeong"] for k, v in sorted(regions.items())})
    return 0


if __name__ == "__main__":
    sys.exit(main())
