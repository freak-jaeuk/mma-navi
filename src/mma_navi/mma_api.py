"""data.go.kr 병무청 오픈API 클라이언트 (표준 라이브러리만).

승인된 엔드포인트:
- 신체검사 정보(3064321): .../jBGSSCJeongBo2/getlist
  문서상 필드: 수검년도, 수검청, 신장, 체중, 시력 — **개인 수검자 단위로 추정**.
  (개인 신장+체중이 한 레코드에 있으면 BMI를 직접 계산 = 결합분포 → 절단 우회 가능성)

주의:
- 실제 XML 태그명은 **첫 성공 호출(probe)로 확인**한 뒤 매핑을 확정한다(추측 하드코딩 금지).
- 네트워크 호출은 이 환경에서 sandbox off로 실행해야 한다.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Dict, List, Optional

SINCHE_GETLIST = "https://apis.data.go.kr/1300000/jBGSSCJeongBo2/getlist"
BMGG_LIST = "https://apis.data.go.kr/1300000/bmggJeongBo/list"  # 사회복무 복무기관(3066757)


class ApiError(RuntimeError):
    pass


def _redact(text: str, secret: Optional[str]) -> str:
    """오류 메시지/본문에서 serviceKey가 새지 않도록 마스킹(원문 + URL-encoded 형태)."""
    if not text or not secret:
        return text
    for form in {secret,
                 urllib.parse.quote(secret, safe=""),
                 urllib.parse.quote_plus(secret)}:
        if form:
            text = text.replace(form, "***REDACTED_KEY***")
    return text


def call_raw(operation_url: str, service_key: Optional[str] = None,
             timeout: int = 40, **params) -> str:
    """오퍼레이션 URL을 호출해 원시 응답 텍스트를 반환."""
    key = service_key or os.environ.get("MMA_SERVICE_KEY")
    if not key:
        raise ApiError("MMA_SERVICE_KEY 없음 (.env 확인 / export 필요)")
    query = urllib.parse.urlencode({"serviceKey": key, **params})
    url = f"{operation_url}?{query}"
    req = urllib.request.Request(url, headers={"Accept": "application/xml"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = _redact(e.read().decode("utf-8", errors="replace"), key)
        raise ApiError(f"HTTP {e.code} {e.reason}: {body[:200]}") from e
    except urllib.error.URLError as e:
        raise ApiError(_redact(f"네트워크 오류: {e.reason}", key)) from e


def parse_items(xml_text: str, service_key: Optional[str] = None) -> List[Dict[str, str]]:
    """data.go.kr 표준 래퍼에서 <item> 레코드들을 추출. 인증/서비스 오류는 ApiError.

    오류 메시지에 본문을 일부 포함할 때 serviceKey가 새지 않도록 redaction한다.
    """
    key = service_key or os.environ.get("MMA_SERVICE_KEY")
    txt = (xml_text or "").strip()
    if not txt:
        raise ApiError("빈 응답")
    low = txt.lower()
    if (low.startswith("unauthorized") or "is not registered" in low
            or ("service key" in low and "error" in low)):
        raise ApiError(_redact(f"인증/키 오류(활성화 지연 가능): {txt[:150]}", key))
    try:
        root = ET.fromstring(txt)
    except ET.ParseError as e:
        raise ApiError(_redact(f"XML 파싱 실패: {e}; 본문 앞부분: {txt[:150]}", key)) from e
    # 표준 응답이면 resultCode 확인
    code = root.findtext(".//resultCode") or root.findtext(".//returnReasonCode")
    if code not in (None, "00", "0"):
        msg = root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or ""
        raise ApiError(_redact(f"서비스 오류 code={code}: {msg}", key))
    return [
        {child.tag: (child.text or "").strip() for child in item}
        for item in root.iter("item")
    ]


def fetch_sinche_records(page_no: int = 1, num_of_rows: int = 100,
                         service_key: Optional[str] = None, **extra) -> List[Dict[str, str]]:
    """신체검사 정보(3064321) 레코드 조회."""
    key = service_key or os.environ.get("MMA_SERVICE_KEY")
    xml = call_raw(SINCHE_GETLIST, service_key=key, pageNo=page_no,
                   numOfRows=num_of_rows, **extra)
    return parse_items(xml, service_key=key)


def fetch_bmgg_records(page_no: int = 1, num_of_rows: int = 100,
                       service_key: Optional[str] = None, **extra) -> List[Dict[str, str]]:
    """사회복무요원 복무기관(3066757) 레코드 조회. 서버측 지역필터 없음(전량 페이징)."""
    key = service_key or os.environ.get("MMA_SERVICE_KEY")
    xml = call_raw(BMGG_LIST, service_key=key, pageNo=page_no,
                   numOfRows=num_of_rows, **extra)
    return parse_items(xml, service_key=key)


def compute_bmi(height_cm: float, weight_kg: float) -> float:
    """BMI = kg / m^2."""
    m = height_cm / 100.0
    if m <= 0:
        raise ValueError("신장은 양수여야 함")
    return weight_kg / (m * m)
