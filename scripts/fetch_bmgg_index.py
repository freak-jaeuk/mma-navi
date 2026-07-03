"""사회복무요원 복무기관(3066757) 전량 수집 → 지방청(gtcdNm)별 인덱스 빌드.

서버측 지역 필터가 없어(전국 22,000여 건) 전체를 페이징해 받아 관할지방청별로
묶는다. 산출 data/bmgg_by_region.json = {지방청: [{nm,addr,sigungu,restrict,disease,tel}, ...]}.
로드맵 4단계(보충역 대비)에서 사용자 지방청의 실제 복무기관을 조회하는 데 쓴다.

실행: MMA_SERVICE_KEY 필요.  python scripts/fetch_bmgg_index.py
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from mma_navi.mma_api import BMGG_LIST, call_raw, parse_items  # noqa: E402

OUT = os.path.join(ROOT, "data", "bmgg_by_region.json")
ROWS = 1000


def _total(xml: str) -> int:
    m = re.search(r"<totalCount>(\d+)</totalCount>", xml or "")
    return int(m.group(1)) if m else 0


def _slim(it: dict) -> dict:
    return {
        "nm": it.get("bokmuGgm", ""),
        "addr": it.get("drmJuso", ""),
        "sigungu": it.get("bjdsgg", ""),
        "restrict": it.get("sbjjehanYn", "") == "Y",
        "disease": it.get("sbjhjilbyeong", ""),
        "tel": it.get("jeonhwaNo", ""),
    }


def main() -> int:
    key = os.environ.get("MMA_SERVICE_KEY")
    if not key:
        print("MMA_SERVICE_KEY 없음 (.env 확인)")
        return 1

    by_region: dict = {}
    page, total, got = 1, None, 0
    while True:
        xml = call_raw(BMGG_LIST, service_key=key, pageNo=page, numOfRows=ROWS)
        if total is None:
            total = _total(xml)
            print(f"총 {total}건, {ROWS}건씩 페이징")
        items = parse_items(xml, service_key=key)
        if not items:
            break
        for it in items:
            region = it.get("gtcdNm", "").strip()
            if not region or not it.get("bokmuGgm"):
                continue
            by_region.setdefault(region, []).append(_slim(it))
        got += len(items)
        print(f"  page {page}: +{len(items)} (누적 {got}/{total})")
        if got >= (total or 0) or len(items) < ROWS:
            break
        page += 1

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    payload = {"_meta": {"total": got, "source": "병무청 사회복무요원 복무기관 API(3066757)",
                         "regions": sorted(by_region)},
               "regions": by_region}
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    sizes = {r: len(v) for r, v in sorted(by_region.items())}
    print(f"\n저장: {OUT}  ({got}건, {len(by_region)}개 지방청)")
    print("지방청별:", sizes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
