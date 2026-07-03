"""실 bge-m3 + 로컬 LLM 통합 테스트 (무거움 — 기본 비활성).

모델을 실제 로드하므로 기본 테스트에서는 건너뛴다. 켜려면:
  MMA_TEST_BGE=1 MMA_RAG=bge-llm MMA_EMBED_DEVICE=cpu MMA_LLM_DEVICE=cuda:0 \
    python tests/test_rag_real.py
(MMA_RAG=bge-extractive로 LLM 없이 검색만 검증도 가능)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

ENABLED = os.environ.get("MMA_TEST_BGE") == "1"

# pytest로 수집되더라도 모델 로드를 막는다(무거움). pytest 미설치 환경도 안전.
try:
    import pytest
    pytestmark = pytest.mark.skipif(not ENABLED, reason="MMA_TEST_BGE=1 로 활성화")
except ImportError:
    pass


def test_bge_retriever_semantic():
    """bge-m3가 조사/어미 변형 질문에서 올바른 문서를 검색하는지(Mock 약점)."""
    if not ENABLED:
        return
    from mma_navi.rag.retriever import BgeRetriever
    import json
    kb_path = os.path.join(os.path.dirname(__file__), "..", "data", "kb_demo.json")
    kb = [(d["text"], d["source"]) for d in json.load(open(kb_path, encoding="utf-8"))]
    r = BgeRetriever(kb)
    docs = r.search("사회복무요원 복무기관은 어떻게 조회하나요?", k=3)
    assert docs and docs[0].score > 0.5
    assert "사회복무" in docs[0].source


def test_e2e_pipeline_answers_and_refuses():
    """실 파이프라인: 절차질문 답변 + 위험질문 거부."""
    if not ENABLED:
        return
    from mma_navi.app import service
    service._get_rag()
    a = service.consult("병역판정검사는 어디서 받나요?")
    assert a["answered"] and a["sources"]
    for q in ["저 현역 갈까요 공익 갈까요?", "디스크 있으면 면제되나요?"]:
        assert not service.consult(q)["answered"]


def test_semantic_teukgi_surfaces_relevant():
    """bge 의미매칭: '보안/정보보호'가 정보보호·사이버 특기를 올린다(포병 X)."""
    if not ENABLED:
        return
    import os
    os.environ.setdefault("MMA_TEUKGI_SEM", "1")
    from mma_navi.app import service
    r = service.recommend_teukgi(interests=["보안", "정보보호"], majors=["컴퓨터공학"])
    assert r["ok"] and r["relevance"] == "bge-m3"
    names = " ".join(m["teukgi_name"] for m in r["matches"])
    assert any(k in names for k in ["정보보호", "사이버", "정보체계", "빅데이터"])


def _run():
    if not ENABLED:
        print("SKIP: MMA_TEST_BGE=1 로 활성화 (모델 로드 무거움)")
        return True
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
