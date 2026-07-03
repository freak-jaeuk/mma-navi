"""모집병 특기 추천 테스트 (픽스처 기반, 네트워크 없이).

실행:  python tests/test_recommend.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.recommend import UserProfile, load_rules_csv, recommend  # noqa: E402

FIX = os.path.join(os.path.dirname(__file__), "..", "data", "fixtures", "teukgi_sample.csv")
RULES = load_rules_csv(FIX)


def _profile():
    return UserProfile(
        majors=["컴퓨터공학"],
        certificates=["정보처리기사"],
        interests=["보안", "네트워크"],
        preferred_branches=["육군", "공군"],
    )


def test_loads_rules():
    assert len(RULES) == 10
    assert any(r.teukgi_name == "정보체계운용" for r in RULES)


def test_qualified_ranked_first():
    res = recommend(_profile(), RULES)
    assert res and res[0].qualifies  # 자격충족이 먼저


def test_certificate_exact_match_qualifies():
    res = recommend(_profile(), RULES)
    hit = [m for m in res if m.matched_on == "정보처리기사"]
    assert hit and hit[0].qualifies
    assert hit[0].rule.teukgi_name == "정보체계운용"


def test_major_match_qualifies():
    res = recommend(_profile(), RULES)
    assert any(m.qualifies and m.matched_on == "컴퓨터공학" for m in res)


def test_branch_filter_excludes_navy():
    res = recommend(_profile(), RULES)
    assert all(m.rule.branch in ("육군", "공군") for m in res)  # 해군 통신 제외


def test_unqualified_marked_check_needed():
    # 정보보안기사 미보유 → 사이버정보보호는 자격 미충족으로 표기(거짓 충족 금지)
    res = recommend(_profile(), RULES, min_relevance=-1.0)  # 전부 포함
    cyber = [m for m in res if m.rule.teukgi_name == "사이버정보보호"]
    if cyber:  # 관련도 낮아 top_k 밖일 수 있음
        assert not cyber[0].qualifies
        assert "확인 필요" in cyber[0].reason


def test_no_pass_guarantee_language():
    res = recommend(_profile(), RULES, top_k=10, min_relevance=-1.0)
    for m in res:
        assert "합격" not in m.reason and "무조건" not in m.reason


def test_grade_requirement_shown():
    res = recommend(_profile(), RULES, top_k=10, min_relevance=-1.0)
    # 기사급이상 같은 등급요건이 사유에 노출되는 케이스가 있어야
    assert any("요건" in m.reason for m in res)


def test_score_grade_blocks_and_passes():
    low = UserProfile(certificates=["토익 500"], interests=["어학"])
    eo = [m for m in recommend(low, RULES, top_k=10, min_relevance=-1.0)
          if m.rule.teukgi_name == "어학"]
    assert eo and not eo[0].qualifies  # 500 < 800점이상 → 미충족
    assert "확인 필요" in eo[0].reason

    high = UserProfile(certificates=["토익 950"], interests=["어학"])
    eo2 = [m for m in recommend(high, RULES, top_k=10, min_relevance=-1.0)
           if m.rule.teukgi_name == "어학"]
    assert eo2 and eo2[0].qualifies  # 950 >= 800


def test_partial_token_does_not_falsely_qualify():
    # '기사'만으로 정보처리기사/전기기사 등에 거짓 자격충족되면 안 됨
    p = UserProfile(certificates=["기사"])
    res = recommend(p, RULES, top_k=10, min_relevance=-1.0)
    for m in res:
        if m.qualifies:
            assert m.matched_on != "기사"


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
