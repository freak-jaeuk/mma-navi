"""mma_api 파서/보안 테스트 (네트워크 없이 문자열로 검증).

실행:  python tests/test_api.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.mma_api import parse_items, _redact, ApiError  # noqa: E402


def test_parse_normal_items():
    xml = ("<response><header><resultCode>00</resultCode></header><body><items>"
           "<item><height>170.5</height><weight>65</weight><jbceong>서울</jbceong></item>"
           "</items></body></response>")
    items = parse_items(xml)
    assert len(items) == 1
    assert items[0]["height"] == "170.5" and items[0]["jbceong"] == "서울"


def test_parse_plaintext_unauthorized():
    try:
        parse_items("Unauthorized")
    except ApiError:
        return
    raise AssertionError("plaintext Unauthorized가 ApiError로 처리되지 않음")


def test_parse_standard_error_xml():
    xml = ("<OpenAPI_ServiceResponse><cmmMsgHeader>"
           "<returnReasonCode>30</returnReasonCode>"
           "<returnAuthMsg>SERVICE_KEY_IS_NOT_REGISTERED_ERROR</returnAuthMsg>"
           "</cmmMsgHeader></OpenAPI_ServiceResponse>")
    try:
        parse_items(xml)
    except ApiError:
        return
    raise AssertionError("표준 에러 XML이 ApiError로 처리되지 않음")


def test_redact_masks_key():
    masked = _redact("error serviceKey=ABC123SECRET in url", "ABC123SECRET")
    assert "ABC123SECRET" not in masked and "REDACTED" in masked


def test_redact_masks_encoded_key():
    import urllib.parse
    key = "ab+c/d=="          # 특수문자 포함 키
    enc = urllib.parse.quote(key, safe="")
    masked = _redact(f"url=...&serviceKey={enc}...", key)
    assert enc not in masked and "REDACTED" in masked


def test_parse_redacts_key_in_error():
    # 200으로 온 본문에 키가 echo된 경우 예외 메시지에 키가 새면 안 됨
    body = "Unauthorized serviceKey=SECRETKEY123 not active"
    try:
        parse_items(body, service_key="SECRETKEY123")
    except ApiError as e:
        assert "SECRETKEY123" not in str(e)
        return
    raise AssertionError("에러로 처리되지 않음")


def _run():
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    passed = 0
    for fn in tests:
        try:
            fn()
        except AssertionError as e:
            print(f"  FAIL  {fn.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {fn.__name__}: {type(e).__name__}: {e}")
        else:
            passed += 1
            print(f"  ok    {fn.__name__}")
    print(f"\n{passed}/{len(tests)} passed")
    return passed == len(tests)


if __name__ == "__main__":
    sys.exit(0 if _run() else 1)
