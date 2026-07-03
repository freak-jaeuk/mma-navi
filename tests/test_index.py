"""특기 인덱스 기반 추천 테스트 (합성 인덱스, 네트워크 없이).

실행:  python tests/test_index.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.recommend import UserProfile, recommend_from_index  # noqa: E402

INDEX = {
    "정보체계운용|육군": {
        "teukgi_code": "15", "teukgi_name": "정보체계운용", "branch": "육군",
        "certs": {"정보처리기사": "기사급이상", "사무자동화산업기사": ""},
        "licenses": {}, "majors": ["컴퓨터공학과", "소프트웨어과"],
    },
    "전자계산|공군": {
        "teukgi_code": "15", "teukgi_name": "전자계산", "branch": "공군",
        "certs": {}, "licenses": {"PC정비사2급": ""}, "majors": ["IT계열", "게임과"],
    },
    "어학|육군": {
        "teukgi_code": "99", "teukgi_name": "어학", "branch": "육군",
        "certs": {"토익": "800점이상"}, "licenses": {}, "majors": [],
    },
    "통신운용|해군": {
        "teukgi_code": "20", "teukgi_name": "통신운용", "branch": "해군",
        "certs": {"정보통신기사": "기사급이상"}, "licenses": {}, "majors": [],
    },
}


def test_certificate_qualifies():
    p = UserProfile(certificates=["정보처리기사"], preferred_branches=["육군", "공군"])
    res = recommend_from_index(p, INDEX)
    assert res and res[0].qualifies
    assert res[0].rule.teukgi_name == "정보체계운용"
    assert res[0].matched_on == "정보처리기사"


def test_score_grade_blocks():
    low = UserProfile(certificates=["토익 500"])
    res = recommend_from_index(low, INDEX, min_relevance=-1.0)
    eo = [m for m in res if m.rule.teukgi_name == "어학"]
    assert eo and not eo[0].qualifies and "확인 필요" in eo[0].reason
    high = UserProfile(certificates=["토익 950"])
    res2 = recommend_from_index(high, INDEX, min_relevance=-1.0)
    eo2 = [m for m in res2 if m.rule.teukgi_name == "어학"]
    assert eo2 and eo2[0].qualifies


def test_branch_filter():
    p = UserProfile(certificates=["정보통신기사"], preferred_branches=["육군", "공군"])
    res = recommend_from_index(p, INDEX, min_relevance=-1.0)
    assert all(m.rule.branch in ("육군", "공군") for m in res)  # 해군 통신 제외


def test_no_false_qualify_partial():
    p = UserProfile(certificates=["기사"])
    res = recommend_from_index(p, INDEX, min_relevance=-1.0)
    for m in res:
        if m.qualifies:
            assert m.matched_on != "기사"


def test_no_pass_language():
    p = UserProfile(certificates=["정보처리기사"], majors=["컴퓨터공학"], interests=["보안"])
    res = recommend_from_index(p, INDEX, top_k=10, min_relevance=-1.0)
    for m in res:
        assert "합격" not in m.reason and "무조건" not in m.reason


def test_aspirational_not_qualified():
    # '정보처리기사 준비중'은 보유가 아니므로 자격충족 처리 금지
    p = UserProfile(certificates=["정보처리기사 준비중"], preferred_branches=["육군"])
    res = recommend_from_index(p, INDEX, min_relevance=-1.0)
    assert all(not m.qualifies for m in res)


def test_unknown_grade_is_verification_required_not_qualified():
    # 해석 불가 등급('일반면허공인')은 후보로 두되 qualifies=False + verification_required
    idx = {"PC정비|공군": {
        "teukgi_code": "1", "teukgi_name": "PC정비", "branch": "공군",
        "certs": {}, "licenses": {"PC정비사2급": "일반면허공인"}, "majors": [],
    }}
    p = UserProfile(certificates=["PC정비사2급"])
    res = recommend_from_index(p, idx, min_relevance=-1.0)
    assert res and not res[0].qualifies          # 검증불가는 '충족' 아님
    assert res[0].verification_required and res[0].status == "unknown"
    assert "본인 확인" in res[0].reason


def test_embedded_score_qualification():
    # 자격명에 점수 내장('토익 900점이상자...')도 보유 점수로 검증
    idx = {"어학|공군": {
        "teukgi_code": "9", "teukgi_name": "어학병", "branch": "공군",
        "certs": {"토익 900점이상자(접수종료 기준 2년이내)": ""}, "licenses": {}, "majors": [],
    }}
    hi = recommend_from_index(UserProfile(certificates=["토익 900"]), idx, min_relevance=-1.0)
    assert hi and hi[0].qualifies and hi[0].status == "ok"
    lo = recommend_from_index(UserProfile(certificates=["토익 850"]), idx, min_relevance=-1.0)
    assert lo and not lo[0].qualifies and lo[0].status == "grade"


def test_rank_grade_shortfall_is_grade_not_leaked():
    # grade_req(급수) 경로 미달: 보유 '전기기사'(rank3) < 요건 '기술사이상'(rank5).
    # 회귀: _grade_check가 'fail'을 흘리면 소비부 grade 분기·tier에 안 걸려
    #       '등급 미충족'이 '관련성' 후보로 조용히 오표기됨.
    idx = {"전기설비|육군": {
        "teukgi_code": "1", "teukgi_name": "전기설비운용", "branch": "육군",
        "certs": {}, "licenses": {"전기기사": "기술사이상"}, "majors": [],
    }}
    res = recommend_from_index(UserProfile(certificates=["전기기사"]), idx, min_relevance=-1.0)
    assert res and not res[0].qualifies and res[0].status == "grade"
    assert "등급" in res[0].reason and "확인 필요" in res[0].reason


def test_dedup_variants():
    idx = {
        "정보체계운용|육군": {"teukgi_code": "15", "teukgi_name": "정보체계운용",
                          "branch": "육군", "certs": {"정보처리기사": ""},
                          "licenses": {}, "majors": []},
        "(맞춤)정보체계운용|육군": {"teukgi_code": "15", "teukgi_name": "(맞춤)정보체계운용",
                              "branch": "육군", "certs": {"정보처리기사": ""},
                              "licenses": {}, "majors": []},
    }
    p = UserProfile(certificates=["정보처리기사"])
    res = recommend_from_index(p, idx, dedup=True)
    assert len(res) == 1  # base 특기명 기준 변형 합쳐짐


def test_branch_alias_haebyeong():
    # 데이터 라벨 '해병' vs UI/일상어 '해병대' — 정규화 안 되면 선호군 필터가 전부 배제(0건 버그)
    idx = {"정보통신|해병": {"teukgi_code": "9", "teukgi_name": "정보통신",
                         "branch": "해병", "certs": {"정보처리기사": ""},
                         "licenses": {}, "majors": []}}
    p = UserProfile(certificates=["정보처리기사"], preferred_branches=["해병대"])
    res = recommend_from_index(p, idx)
    assert len(res) == 1 and res[0].rule.teukgi_name == "정보통신"


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
