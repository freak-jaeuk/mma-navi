"""통합 서비스 레이어 테스트 (app/service.py) — 네트워크/서버 없이 검증.

실행:  python tests/test_service.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.app import service  # noqa: E402


def test_status():
    s = service.status()
    assert s["ok"] and s["cohort_size"] > 0 and s["teukgi_count"] > 0


def test_cohorts_default_first():
    cs = service.list_cohorts()
    assert cs and cs[0] == service.DEFAULT_COHORT


def test_percentile_normal():
    r = service.percentile_report(174, 68)
    assert r["ok"] and r["bmi"] > 0
    labels = {b["label"]: b for b in r["blocks"]}
    assert labels["BMI"]["ok"] and 0 <= labels["BMI"]["percentile_rank"] <= 100


def test_percentile_out_of_range_abstains():
    r = service.percentile_report(250, 20)   # 신장 초과 / 체중·BMI 미만
    blocks = {b["label"]: b for b in r["blocks"]}
    assert not blocks["신장"]["ok"] and blocks["신장"]["abstain_reason"] == "above_max"
    assert not blocks["체중"]["ok"] and blocks["체중"]["abstain_reason"] == "below_min"


def test_percentile_bad_input():
    assert service.percentile_report("x", 60)["ok"] is False
    assert service.percentile_report(0, 60)["ok"] is False
    assert service.percentile_report(-1, 60)["ok"] is False


def test_percentile_unknown_cohort_falls_back():
    r = service.percentile_report(174, 68, cohort="없는코호트")
    assert r["ok"] and r["cohort"] == service.DEFAULT_COHORT


def test_consult_answers_procedural():
    r = service.consult("병역판정검사는 어디서 받나요?")
    assert r["ok"] and r["answered"] and r["sources"]


def test_consult_refuses_individual():
    r = service.consult("저 현역 갈까요 공익 갈까요?")
    assert r["ok"] and not r["answered"]
    assert r["refusal_reason"] == "개인판정" and r["alternatives"]


def test_consult_refuses_medical_and_prediction():
    assert service.consult("제 디스크면 면제 되나요?")["refusal_reason"] == "의료진단"
    assert service.consult("저 이번에 모집병 붙을까요?")["refusal_reason"] == "합격예측"


def test_consult_empty():
    assert service.consult("   ")["ok"] is False


def test_teukgi_recommend():
    r = service.recommend_teukgi(majors=["컴퓨터공학"], certificates=["정보처리기사"])
    assert r["ok"] and r["matches"]
    assert r["n_total_teukgi"] > 0
    # 검증충족(ok)은 qualifies=True
    for m in r["matches"]:
        if m["status"] == "ok":
            assert m["qualifies"] is True


def test_teukgi_empty_profile():
    assert service.recommend_teukgi()["ok"] is False


def test_roadmap_normal_cites_results():
    r = service.roadmap_report(174, 68, majors=["컴퓨터공학"], certificates=["정보처리기사"])
    assert r["ok"]
    steps = r["roadmap"]["steps"]
    assert len(steps) == 5 and [s["n"] for s in steps] == [1, 2, 3, 4, 5]
    # 2단계는 백분위 인용(범위 내 → ok 톤), 각 단계에 링크/후속질문
    assert steps[1]["tone"] in ("ok", "warn", "info")
    for s in steps:
        assert s["link"]["url"].startswith("https://") and s["ask"]


def test_roadmap_out_of_range_warns():
    r = service.roadmap_report(250, 20, majors=["전자공학"])  # 범위 밖
    assert r["ok"]
    s2 = r["roadmap"]["steps"][1]
    assert s2["tone"] == "warn" and "보류" in s2["text"]


def test_roadmap_no_profile_skips_teukgi():
    r = service.roadmap_report(174, 68)  # 전공/자격 없음
    assert r["ok"] and r["teukgi"].get("skipped")
    # 3단계는 '입력하면 추천' 안내(info)
    assert r["roadmap"]["steps"][2]["tone"] == "info"


def test_roadmap_bad_input():
    r = service.roadmap_report("x", 68)
    assert r["ok"] is False and r["stage"] == "percentile"


def test_classify_query():
    r = service.classify_query("모집병 특기 추천해줘")
    assert r["ok"] and r["category"] == "모집병"
    assert service.classify_query("  ")["ok"] is False


def test_build_roadmap_unit():
    # 직접 단위: 범위밖 백분위 + 등급미달 특기 → warn 단계 + 보완 안내
    pr = {"ok": True, "cohort": "2026_전국", "height_cm": 250, "weight_kg": 20, "bmi": 3.2,
          "blocks": [{"metric": "bmi", "label": "BMI", "ok": False, "abstain_reason": "below_min"}]}
    tr = {"ok": True, "matches": [
        {"teukgi_name": "통신", "branch": "육군", "status": "grade",
         "qualification": "정보처리기사", "grade_req": "기사급이상"}]}
    rm = service.build_roadmap({"cohort": "2026_전국"}, pr, tr)
    assert rm["ok"] and len(rm["steps"]) == 5
    assert rm["steps"][1]["tone"] == "warn"
    assert "통신" in rm["steps"][3]["text"]  # 4단계 자격 보완 인용


def test_build_roadmap_unknown_separated_from_ok():
    # unknown(본인확인 필요)은 'ok 톤·1순위'로 올리지 않는다(정직성).
    pr = {"ok": True, "cohort": "2026_전국", "bmi": 22.0,
          "blocks": [{"metric": "bmi", "label": "BMI", "ok": True, "percentile_rank": 40.0}]}
    tr = {"ok": True, "matches": [
        {"teukgi_name": "통신", "branch": "육군", "status": "unknown",
         "qualification": "토익", "grade_req": ""}]}
    rm = service.build_roadmap({}, pr, tr)
    s3 = rm["steps"][2]
    assert s3["tone"] == "warn" and "본인 확인" in s3["text"]
    assert "1순위" not in s3["text"]


def test_build_roadmap_missing_keys_safe():
    # 키가 일부 빠진 dict가 와도 KeyError 없이 동작(방어).
    pr = {"ok": True, "cohort": "2026_전국",
          "blocks": [{"metric": "bmi", "ok": False, "abstain_reason": "below_min"}]}  # label 없음
    tr = {"ok": True, "matches": [{"status": "ok"}]}  # teukgi_name/branch 없음
    rm = service.build_roadmap({}, pr, tr)
    assert rm["ok"] and len(rm["steps"]) == 5


def test_b2g_heatmap_bmi():
    r = service.b2g_heatmap("bmi")
    assert r["ok"] and r["metric"] == "bmi"
    assert r["national"]["n"] > 0 and r["national"]["median"] > 0
    assert len(r["rows"]) >= 10        # 14지방청
    for row in r["rows"]:
        assert row["median"] > 0 and row["n"] > 0
        assert row["over25"] is None or 0 <= row["over25"] <= 100
    # 중앙값 내림차순 정렬
    meds = [row["median"] for row in r["rows"]]
    assert meds == sorted(meds, reverse=True)


def test_b2g_heatmap_height_no_bmi_fields():
    r = service.b2g_heatmap("height")
    assert r["ok"] and r["metric"] == "height"
    assert "over25" not in r["rows"][0]   # 신장은 비만비율 없음


def test_b2g_bad_metric_falls_back():
    assert service.b2g_heatmap("없는지표")["metric"] == "bmi"


def test_b2g_bmi_overlay_and_year():
    r = service.b2g_heatmap("bmi")
    assert r["data_year"] and r["reference"] and r["reference"]["metric"] == "bmi"
    assert 0 <= r["national"]["over25"] <= 100   # 전국 과체중+ 비율
    assert "caveat" in r["reference"]            # 직접비교 주의 명시


def test_b2g_height_no_reference():
    assert service.b2g_heatmap("height")["reference"] is None


def test_complaint_stats():
    r = service.complaint_stats()
    assert r["ok"] and r["total"] > 0
    assert r["auto_refuse"] + r["answerable"] == r["total"]
    cats = {d["category"] for d in r["distribution"]}
    assert {"신검", "모집병"} & cats        # 주요 유형 포함
    assert sum(d["count"] for d in r["distribution"]) == r["total"]


def test_rag_backend_fallback_mock(monkeypatch=None):
    # MMA_RAG 미설정/mock이면 mock으로 동작(모델 로드 없이)
    import os
    if os.environ.get("MMA_RAG", "mock").lower() == "mock":
        r = service.consult("병역판정검사는 어디서 받나요?")
        assert r["ok"] and "backend" in r


def test_metrics_loads():
    r = service.metrics()
    # report.json이 있으면 dev 섹션 포함
    assert r["ok"] in (True, False)
    if r["ok"]:
        assert "dev" in r["report"] or "holdout" in r["report"]


def test_social_agencies_match_and_fallback():
    saved = service._bmgg_regions
    try:
        service._bmgg_regions = {"충북": [
            {"nm": "A센터", "addr": "충북 청주", "sigungu": "청주시 흥덕구",
             "restrict": True, "disease": "정신과질환", "tel": "043-1"},
            {"nm": "B복지관", "addr": "충북 충주", "sigungu": "충주시",
             "restrict": False, "disease": "", "tel": "043-2"}]}
        ag = service.social_agencies("충북", limit=1)
        assert ag and ag["region"] == "충북" and ag["total"] == 2
        assert len(ag["items"]) == 1 and ag["items"][0]["nm"] == "A센터"  # limit 적용
        assert "3066757" in ag["source"] and ag["caveat"]                # 출처·정직 캡션
        assert service.social_agencies("전국") is None                    # 미매칭 → 폴백
        assert service.social_agencies("") is None
    finally:
        service._bmgg_regions = saved


def test_roadmap_step4_attaches_agencies_when_available():
    saved = service._bmgg_regions
    try:
        service._bmgg_regions = {"충북": [{"nm": "행복센터", "addr": "충북 단양",
                                          "sigungu": "단양군", "restrict": True,
                                          "disease": "", "tel": "043"}]}
        r = service.roadmap_report(174, 68, cohort="2026_충북")
        s4 = [s for s in r["roadmap"]["steps"] if s["n"] == 4][0]
        assert s4.get("agencies") and s4["agencies"]["total"] == 1
        assert "행복센터" in s4["text"]                                   # 예시 기관명 인용
        r2 = service.roadmap_report(174, 68, cohort="2026_전국")
        assert [s for s in r2["roadmap"]["steps"] if s["n"] == 4][0].get("agencies") is None
    finally:
        service._bmgg_regions = saved


def test_career_centers_and_roadmap_step5():
    saved = service._jinro_centers
    try:
        service._jinro_centers = {"충북": [{"name": "청주센터", "addr": "충북 청주시 ...",
                                          "tel": "043-1", "note": ""}]}
        c = service.career_centers("충북")
        assert c and c["centers"][0]["name"] == "청주센터" and "15148370" in c["source"]
        assert service.career_centers("없는지방청") is None       # 미매칭 → 폴백(공식 링크)
        r = service.roadmap_report(174, 68, cohort="2026_충북")
        s5 = [s for s in r["roadmap"]["steps"] if s["n"] == 5][0]
        assert s5.get("centers") and "청주센터" in s5["text"]      # 실 센터 인용
    finally:
        service._jinro_centers = saved


def test_social_vacancies_match_and_fallback():
    saved = service._gongseok_regions
    try:
        service._gongseok_regions = {"경남": {"baejeong": 120, "records": 45, "sample": [
            {"gigwan": "경남혜림학교", "sigungu": "창원시", "baejeong": 1, "tms": 1, "type": "본인선택"}]}}
        v = service.social_vacancies("경남")
        assert v and v["region"] == "경남" and v["baejeong"] == 120 and v["records"] == 45
        assert "3066754" in v["source"] and "예측" in v["caveat"]
        assert service.social_vacancies("전국") is None       # 미매칭 → 폴백
        assert service.social_vacancies("") is None
    finally:
        service._gongseok_regions = saved


def test_convocation_plan_and_fallback():
    saved = service._sojip_plan
    try:
        service._sojip_plan = {"_meta": {"year": "2026", "total_pcnt": 100,
                                         "field_count": 2, "source": "병무청 ...(3066753)"},
                               "fields": [{"name": "사회복지시설 운영지원", "pcnt": 70, "agencies": 5},
                                          {"name": "일반행정 지원", "pcnt": 30, "agencies": 3}]}
        p = service.convocation_plan(top=1)
        assert p["year"] == "2026" and p["total_pcnt"] == 100
        assert len(p["top_fields"]) == 1 and p["top_fields"][0]["pcnt"] == 70  # 인원순·top 적용
        service._sojip_plan = {}                       # 미수집 → None 폴백
        assert service.convocation_plan() is None
    finally:
        service._sojip_plan = saved


def test_teukgi_competition_dedup_gun_and_validation():
    # 실제 파일로드 경로로 검증: (특기명,군) 키·모호 제외·무효 rate 제외·군 분리
    import json
    import tempfile
    saved_path, saved_cache = service.JEOPSU_RATE, service._jeopsu_rates
    fd, tmp = tempfile.mkstemp(suffix=".json")
    try:
        recs = [
            {"name": "포병레이더", "gun": "육군", "rate": "2", "jeopsu": 40, "seonbal": 20, "yy": 2025, "tms": 2},
            # 모호: 괄호 떼면 같은 (정규화명,군)에 다른 경쟁률 → 제외
            {"name": "장애물운용(E)", "gun": "육군", "rate": "1.5", "jeopsu": 30, "seonbal": 20, "yy": 2025, "tms": 1},
            {"name": "장애물운용(M)", "gun": "육군", "rate": "3.0", "jeopsu": 60, "seonbal": 20, "yy": 2025, "tms": 1},
            {"name": "어학병", "gun": "해군", "rate": "*", "jeopsu": 5, "seonbal": 5, "yy": 2025, "tms": 2},   # 무효 rate
            {"name": "통신", "gun": "공군", "rate": "1", "jeopsu": 10, "seonbal": 0, "yy": 2025, "tms": 2},     # 선발 0
            {"name": "일반", "gun": "해군", "rate": "4", "jeopsu": 40, "seonbal": 10, "yy": 2025, "tms": 2},
            {"name": "일반", "gun": "공군", "rate": "7", "jeopsu": 70, "seonbal": 10, "yy": 2025, "tms": 2},
        ]
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"records": recs}, f, ensure_ascii=False)
        service.JEOPSU_RATE = tmp
        service._jeopsu_rates = None
        assert service.teukgi_competition("포병레이더(연모집)", "육군")["rate"] == 2.0  # 괄호 정규화 매칭
        assert service.teukgi_competition("장애물운용", "육군") is None    # 모호 → 제외
        assert service.teukgi_competition("어학병", "해군") is None        # rate '*' → 제외
        assert service.teukgi_competition("통신", "공군") is None          # 선발 0 → 제외
        assert service.teukgi_competition("일반", "해군")["rate"] == 4.0   # 동명 이군 분리
        assert service.teukgi_competition("일반", "공군")["rate"] == 7.0
        assert service.teukgi_competition("포병레이더", "해군") is None    # 군 불일치 → 미표시
    finally:
        service.JEOPSU_RATE, service._jeopsu_rates = saved_path, saved_cache
        os.remove(tmp)


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
