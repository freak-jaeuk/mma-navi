"""모집병 특기 규칙 로딩 (3066750 API / 픽스처 CSV).

CSV·API 모두 동일 필드명(gsteukgiCd 등)을 쓰므로 같은 매핑으로 처리한다.
3066750은 서버측 검색 파라미터가 없어 전체를 받아 클라이언트에서 매칭한다(규모 작음).
"""
from __future__ import annotations

import csv
import os
import xml.etree.ElementTree as ET
from typing import List, Optional

from .teukgi import TeukgiRule

MOJIB_LIST = "https://apis.data.go.kr/1300000/mjbJiWon/list"


def _rule_from_item(item: dict) -> TeukgiRule:
    return TeukgiRule(
        teukgi_code=(item.get("gsteukgiCd") or "").strip(),
        teukgi_name=(item.get("gsteukgiNm") or "").strip(),
        branch=(item.get("gtcdNm1") or "").strip(),
        qualification=(item.get("gtcdNm2") or "").strip(),
        qual_type=(item.get("gubun") or "").strip(),
        grade_req=(item.get("jgmyeonheoDg") or "").strip(),
        direct_indirect=(item.get("jjganjeopGbcd") or "").strip(),
    )


def load_rules_csv(path: str) -> List[TeukgiRule]:
    with open(path, newline="", encoding="utf-8") as f:
        return [_rule_from_item(row) for row in csv.DictReader(f)]


def fetch_rules_api(max_pages: int = 30, rows: int = 1000,
                    service_key: Optional[str] = None) -> List[TeukgiRule]:
    """3066750에서 전체 특기 규칙을 받아온다(활성화 후)."""
    from ..mma_api import call_raw, parse_items
    key = service_key or os.environ.get("MMA_SERVICE_KEY")
    rules: List[TeukgiRule] = []
    total = None
    for page in range(1, max_pages + 1):
        xml = call_raw(MOJIB_LIST, service_key=key, pageNo=page, numOfRows=rows)
        # 먼저 parse_items로 검증+redaction(에러 경로 우회 방지). 성공 시 XML 유효.
        items = parse_items(xml, service_key=key)
        if total is None:
            try:
                t = ET.fromstring(xml).findtext(".//totalCount")
                total = int(t) if t else None
            except (ET.ParseError, ValueError):
                total = None
        if not items:           # 빈 페이지 = 종료(주 종료조건)
            break
        rules.extend(_rule_from_item(i) for i in items)
        if total and len(rules) >= total:   # totalCount는 보조 종료조건
            break
    return rules
