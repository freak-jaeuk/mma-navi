"""모집병 군지원 접수현황(15031295) 전량 수집 → 특기별 '최근 회차' 경쟁률 맵.

시계열 아카이브가 아닌 스냅샷이므로 특기(gsteukgiNm)별로 가장 최근 회차
(mojipYy, mojipTms) 1건만 남긴다. 산출 data/jeopsu_rate.json =
{특기명: {rate, jeopsu, seonbal, gun, yy, tms}}. 특기 추천 화면에 '최근 회차
경쟁률(참고·예측 아님)'로 표시한다.

실행: MMA_SERVICE_KEY 필요.  python scripts/fetch_jeopsu_rate.py
"""
import json
import os
import re
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))

from mma_navi.mma_api import call_raw, parse_items  # noqa: E402

ENDPOINT = "https://apis.data.go.kr/1300000/MJBGJWJeopSuHH4/list"
OUT = os.path.join(ROOT, "data", "jeopsu_rate.json")
ROWS = 1000


def _total(xml: str) -> int:
    m = re.search(r"<totalCount>(\d+)</totalCount>", xml or "")
    return int(m.group(1)) if m else 0


def _int(s) -> int:
    try:
        return int(str(s).strip())
    except (TypeError, ValueError):
        return 0


def _seq(it: dict) -> tuple:
    """회차 최신성 비교키 (년도, 회차)."""
    return (_int(it.get("mojipYy")), _int(it.get("mojipTms")))


def main() -> int:
    if not os.environ.get("MMA_SERVICE_KEY"):
        print("MMA_SERVICE_KEY 없음")
        return 1
    # (특기명, 군) 단위로 가장 최근 회차만 유지 — 서로 다른 모집단위(군/임기제/연모집)를
    # 섞지 않는다. 매칭 정규화·모호성 제거는 service에서 수행(틀린 값보다 미표시가 정직).
    latest: dict = {}          # (name, gun) → (seq, record)
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
            name = (it.get("gsteukgiNm") or "").strip()
            gun = (it.get("gunGbnm") or "").strip()
            if not name:
                continue
            key = (name, gun)
            seq = _seq(it)
            if key not in latest or seq > latest[key][0]:
                latest[key] = (seq, {
                    "name": name, "gun": gun,
                    "rate": (it.get("rate") or "").strip(),
                    "jeopsu": _int(it.get("jeopsuPcnt")),
                    "seonbal": _int(it.get("seonbalPcnt")),
                    "yy": _int(it.get("mojipYy")),
                    "tms": _int(it.get("mojipTms")),
                })
        got += len(items)
        print(f"  page {page}: +{len(items)} ({got}/{total})")
        if got >= (total or 0) or len(items) < ROWS:
            break
        page += 1

    records = [rec for _seq_, rec in latest.values()]
    payload = {"_meta": {"specialty_count": len(records), "records_scanned": got,
                         "source": "병무청 모집병 군지원 접수현황 API(15031295)",
                         "caveat": "모집 스냅샷 경쟁률(참고용, 합격/선발 예측 아님)."},
               "records": records}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False)
    print(f"\n저장: {OUT}  ({len(records)}개 (특기,군))")
    print("예:", [(r["name"], r["gun"], r["rate"], f"{r['jeopsu']}/{r['seonbal']}")
                for r in records[:5]])
    return 0


if __name__ == "__main__":
    sys.exit(main())
