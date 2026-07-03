"""모집병 특기(3066750) 전량 수집 → 특기 단위 컴팩트 인덱스 빌드.

1.36M행을 매 질의마다 훑지 않도록 (특기명|군) 단위로 집계:
  certs    : {자격명: 등급}      (결정론 매칭)
  licenses : {면허명: 등급}      (결정론 매칭)
  majors   : [전공명...]         (관련도 매칭)
산출: data/teukgi_index.json

실행(네트워크, sandbox off):  python scripts/fetch_teukgi_index.py
"""
import json
import os
import sys
import time
import xml.etree.ElementTree as ET

ROOT = "/home/kimjw/workspace/mma-contest"
sys.path.insert(0, os.path.join(ROOT, "src"))
OUT = os.path.join(ROOT, "data", "teukgi_index.json")
URL = "https://apis.data.go.kr/1300000/mjbJiWon/list"


def _load_env():
    if os.environ.get("MMA_SERVICE_KEY"):
        return
    p = os.path.join(ROOT, ".env")
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    _load_env()
    from mma_navi.mma_api import call_raw, parse_items

    from mma_navi.mma_api import ApiError

    def call_retry(page, attempts=5):
        for a in range(attempts):
            try:
                return call_raw(URL, service_key=key, pageNo=page, numOfRows=rows)
            except ApiError as ex:
                msg = str(ex)
                transient = any(c in msg for c in ("502", "503", "504", "네트워크", "timed out"))
                if transient and a < attempts - 1:
                    time.sleep(2 * (a + 1))
                    continue
                raise

    key = os.environ["MMA_SERVICE_KEY"]
    index = {}
    seen = 0
    total = None
    rows = 5000
    for page in range(1, 400):
        xml = call_retry(page)
        items = parse_items(xml, service_key=key)
        if total is None:
            t = ET.fromstring(xml).findtext(".//totalCount")
            total = int(t) if t else None
        if not items:
            break
        for it in items:
            name = (it.get("gsteukgiNm") or "").strip()
            branch = (it.get("gtcdNm1") or "").strip()
            if not name:
                continue
            k = f"{name}|{branch}"
            e = index.setdefault(k, {
                "teukgi_code": (it.get("gsteukgiCd") or "").strip(),
                "teukgi_name": name, "branch": branch,
                "certs": {}, "licenses": {}, "majors": [],
            })
            gubun = (it.get("gubun") or "").strip()
            qname = (it.get("gtcdNm2") or "").strip()
            grade = (it.get("jgmyeonheoDg") or "").strip()
            if not qname:
                continue
            if gubun == "자격":
                e["certs"][qname] = grade
            elif gubun == "면허":
                e["licenses"][qname] = grade
            elif gubun == "전공":
                if qname not in e["majors"]:
                    e["majors"].append(qname)
        seen += len(items)
        if page % 20 == 0:
            print(f"  ...{seen}/{total}")
        if total and seen >= total:
            break

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False)
    size_mb = os.path.getsize(OUT) / 1e6
    n_cert = sum(len(e["certs"]) for e in index.values())
    n_lic = sum(len(e["licenses"]) for e in index.values())
    n_maj = sum(len(e["majors"]) for e in index.values())
    print(f"\n수집 {seen}행 → 인덱스 {len(index)}개 특기(군별)")
    print(f"자격 {n_cert} / 면허 {n_lic} / 전공 {n_maj}  | {OUT} ({size_mb:.1f}MB)")
    print("군:", sorted({e['branch'] for e in index.values()}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
