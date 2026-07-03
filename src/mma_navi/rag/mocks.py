"""오프라인 테스트용 Mock Retriever/LLM.

실제 구현(bge-m3 임베딩 검색 + 로컬 LLM 생성)을 붙이기 전에 거부 게이트 로직을
환경 의존 없이 검증하기 위한 더미. 인터페이스(search/generate)만 맞추면 교체 가능.
"""
from __future__ import annotations

from typing import List, Sequence, Tuple

from .gates import tokens
from .pipeline import RetrievedDoc


class MockRetriever:
    """질문-문서 토큰 겹침(질문 커버율)으로 점수 매기는 더미 검색기."""

    def __init__(self, kb: Sequence[Tuple[str, str]]):
        self.kb = list(kb)  # (text, source)

    def search(self, query: str, k: int = 5) -> List[RetrievedDoc]:
        qt = tokens(query)
        scored = []
        for text, source in self.kb:
            dt = tokens(text)
            score = (len(qt & dt) / len(qt)) if qt else 0.0
            scored.append(RetrievedDoc(text=text, source=source, score=round(score, 3)))
        scored.sort(key=lambda d: d.score, reverse=True)
        return scored[:k]


class MockLLM:
    """근거(top context)를 그대로 반환 → grounded & deterministic(일관)."""

    def generate(self, query: str, contexts: Sequence[RetrievedDoc]) -> str:
        return contexts[0].text if contexts else ""


class InconsistentLLM:
    """호출마다 상호 무관한 답을 돌려 자기일관성 게이트를 일부러 실패시킴."""

    def __init__(self):
        self._answers = [
            "모집병 지원은 온라인으로 접수합니다",
            "병역판정검사는 지정 병원에서 받습니다",
            "여비는 교통비 기준으로 지급됩니다",
        ]
        self._i = 0

    def generate(self, query: str, contexts: Sequence[RetrievedDoc]) -> str:
        a = self._answers[self._i % len(self._answers)]
        self._i += 1
        return a


class UnfaithfulLLM:
    """근거와 무관한 답을 일관되게 반환 → 근거율 게이트를 실패시킴."""

    def generate(self, query: str, contexts: Sequence[RetrievedDoc]) -> str:
        return "라면 우주 고양이 자동차 무관한 내용입니다"
