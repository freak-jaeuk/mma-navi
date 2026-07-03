"""상담 RAG + 거부 게이트 테스트 (네트워크/모델 없이 mock으로).

실행:  python tests/test_rag.py
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from mma_navi.rag import (  # noqa: E402
    InconsistentLLM,
    MockLLM,
    MockRetriever,
    RagPipeline,
    RefusalReason,
    REFUSAL_MESSAGES,
    UnfaithfulLLM,
    intent_gate,
)

KB = [
    ("병역판정검사 전에는 신분증과 검사 통지서를 준비하고 충분한 수면을 취하세요.", "병무청 신검 안내"),
    ("모집병 지원은 지원 자격 확인, 온라인 접수, 선발 절차 순으로 진행됩니다.", "병무청 모집병 안내"),
    ("사회복무요원 복무기관은 병무청 누리집에서 지역별로 조회할 수 있습니다.", "병무청 사회복무 안내"),
]


def pipe(llm=None):
    return RagPipeline(MockRetriever(KB), llm or MockLLM())


def test_answerable():
    r = pipe().answer("모집병 지원 절차 알려줘")
    assert r.answered and r.sources
    assert r.grounding is not None and r.grounding >= 0.5
    assert "모집병" in r.sources[0].text


def test_refuse_individual_judgment():
    r = pipe().answer("나 BMI 높은데 4급 가능해?")
    assert not r.answered
    assert r.refusal_reason == RefusalReason.INDIVIDUAL_JUDGMENT
    assert r.alternatives and r.refusal_message  # 대체 안내 + 사유 문구


def test_refuse_pass_prediction():
    r = pipe().answer("이 특기 합격 가능성 높아?")
    assert not r.answered and r.refusal_reason == RefusalReason.PASS_PREDICTION


def test_refuse_medical():
    r = pipe().answer("이거 무슨 병이야?")
    assert not r.answered and r.refusal_reason == RefusalReason.MEDICAL_DIAGNOSIS


def test_refuse_no_evidence():
    r = pipe().answer("오늘 점심 메뉴 추천해줘")
    assert not r.answered and r.refusal_reason == RefusalReason.NO_EVIDENCE


def test_refuse_inconsistent():
    r = pipe(InconsistentLLM()).answer("모집병 지원 절차 알려줘")
    assert not r.answered and r.refusal_reason == RefusalReason.INCONSISTENT
    assert r.consistency_ok is False


def test_refuse_unfaithful():
    r = pipe(UnfaithfulLLM()).answer("모집병 지원 절차 알려줘")
    assert not r.answered and r.refusal_reason == RefusalReason.NO_EVIDENCE
    assert r.grounding is not None and r.grounding < 0.5


def test_intent_gate_allows_normal():
    assert intent_gate("모집병 지원 절차 알려줘") is None
    assert intent_gate("병역판정검사 준비물이 뭐야?") is None


def test_all_refusals_have_alternatives():
    for reason, (msg, alts) in REFUSAL_MESSAGES.items():
        assert msg and alts, f"{reason} 사유 문구/대체안내 누락"


def test_trust_status_label():
    r = pipe().answer("모집병 지원 절차 알려줘")
    assert "근거" in r.trust_status


def test_intent_gate_catches_dangerous_phrasings():
    dangerous = [
        "저는 현역 갈까요", "저 공익 가능?", "정신과 다니는데 면제되나요",
        "신검 통과할 수 있나요?", "군대 안 갈 수 있나요?", "신체등급 알려줘",
        "병역처분 예측해줘", "나 4급 나올까?",
    ]
    for q in dangerous:
        assert intent_gate(q) is not None, f"위험 질문 놓침: {q}"


def test_intent_gate_allows_procedural():
    safe = [
        "신검 전 준비할 게 뭐야?", "모집병 지원 절차 알려줘",
        "사회복무기관 어디서 확인해?", "병역판정검사 준비물이 뭐야?",
        "입영 날짜는 어떻게 확인해?", "현역 자원이 왜 줄어들어?",
    ]
    for q in safe:
        assert intent_gate(q) is None, f"정상 질문 오거부: {q}"


def test_degenerate_answer_refused():
    class OneWord:
        def generate(self, q, ctx):
            return "모집병"
    from mma_navi.rag import RagPipeline
    r = RagPipeline(MockRetriever(KB), OneWord()).answer("모집병 지원 절차 알려줘")
    assert not r.answered and r.refusal_reason == RefusalReason.NO_EVIDENCE


def test_semantic_consistency_paraphrase_vs_divergent():
    import numpy as np
    from mma_navi.rag.gates import self_consistency, semantic_consistency
    # 같은 뜻·다른 표현(토큰 거의 안 겹침): 임베딩 코사인은 높고 lexical은 낮다
    para = ["온라인으로 접수하세요", "인터넷 신청으로 진행하면 됩니다"]
    pvec = {para[0]: [1.0, 0.02], para[1]: [0.98, 0.05]}
    assert semantic_consistency(
        para, lambda t: np.array([pvec[x] for x in t], dtype="float32"), 0.8) is True
    assert self_consistency(para, 0.45) is False        # lexical이면 오거부(대비 근거)
    # 뜻이 갈리는 답변: 코사인 낮음 → 불일치
    div = ["접수는 온라인으로 합니다", "준비물은 신분증입니다"]
    dvec = {div[0]: [1.0, 0.0], div[1]: [0.0, 1.0]}
    assert semantic_consistency(
        div, lambda t: np.array([dvec[x] for x in t], dtype="float32"), 0.8) is False


def test_semantic_consistency_falls_back_on_embed_error():
    import numpy as np
    from mma_navi.rag.gates import semantic_consistency

    def boom(texts):
        raise RuntimeError("임베딩 모델 없음")
    same = ["모집병 지원은 온라인 접수", "모집병 지원은 온라인 접수"]
    assert semantic_consistency(same, boom, 0.8) is True     # lexical 폴백: 동일 → 일관
    diff = ["모집병 지원은 온라인 접수 절차입니다", "여비 신청은 계좌 등록 후 지급됩니다"]
    assert semantic_consistency(diff, boom, 0.8) is False    # lexical 폴백: 불일치
    # NaN·0벡터 임베딩도 조용히 불일치되지 않고 lexical 폴백(동일 문자열 → 일관)
    assert semantic_consistency(same, lambda t: np.full((len(t), 2), np.nan, "float32"), 0.8) is True
    assert semantic_consistency(same, lambda t: np.zeros((len(t), 2), "float32"), 0.8) is True


def test_pipeline_uses_injected_consistency_fn():
    q = "모집병 지원 절차 알려줘"
    r_no = RagPipeline(MockRetriever(KB), MockLLM(),
                       consistency_fn=lambda s: False).answer(q)
    assert not r_no.answered and r_no.refusal_reason == RefusalReason.INCONSISTENT
    r_yes = RagPipeline(MockRetriever(KB), MockLLM(),
                        consistency_fn=lambda s: True).answer(q)
    assert r_yes.answered


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
