"""상담 RAG 파이프라인 — 의도/근거/일관성/근거율 게이트로 답하거나 거부한다.

흐름:
  1) 의도 게이트: 개인판정/의료진단/합격예측 질문이면 즉시 거부(+대체 안내)
  2) 검색: 근거 문서 없음/임계 미달이면 근거부족 거부
  3) 생성(자기일관성): LLM을 N회 샘플 → 불일치면 불확실 거부
  4) 근거율 게이트: 답변이 근거에 충분히 기반하지 않으면 근거부족 거부
  5) 통과 시 답변 + 출처 반환 (근거 출처 패널용 메타 포함)

Retriever/LLM은 인터페이스(덕타이핑). 실제 구현(bge-m3 + 로컬 LLM)은 추후 주입.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Callable, List, Optional, Protocol, Sequence

from .gates import (
    REFUSAL_MESSAGES,
    RefusalReason,
    grounding_ratio,
    intent_gate,
    self_consistency,
    token_list,
)


def _is_degenerate(answer: str, min_tokens: int = 4, max_repeat_ratio: float = 0.5) -> bool:
    """부실 답변(너무 짧거나 토큰 반복 과다)인지 — lexical 게이트 우회 방지."""
    toks = token_list(answer)
    if len(toks) < min_tokens:
        return True
    if len(set(toks)) / len(toks) < max_repeat_ratio:
        return True
    return False


@dataclass(frozen=True)
class RetrievedDoc:
    text: str
    source: str
    score: float


class Retriever(Protocol):
    def search(self, query: str, k: int = 5) -> List[RetrievedDoc]:
        ...


class LLM(Protocol):
    def generate(self, query: str, contexts: Sequence[RetrievedDoc]) -> str:
        ...


@dataclass(frozen=True)
class RagResult:
    answered: bool
    answer: Optional[str] = None
    refusal_reason: Optional[RefusalReason] = None
    refusal_message: Optional[str] = None
    alternatives: List[str] = field(default_factory=list)
    sources: List[RetrievedDoc] = field(default_factory=list)
    grounding: Optional[float] = None      # 근거율(0~1)
    consistency_ok: Optional[bool] = None  # 자기일관성 통과 여부

    @property
    def trust_status(self) -> str:
        """근거 출처 패널의 '신뢰 상태' 라벨(거부게이트 판정값으로 구동)."""
        if not self.answered:
            return f"공식판단 필요/근거 부족 ({self.refusal_reason.value})"
        if (self.grounding or 0) >= 0.75:
            return "근거 충분"
        return "근거 부분적"


def _refuse(reason: RefusalReason) -> RagResult:
    msg, alts = REFUSAL_MESSAGES[reason]
    return RagResult(answered=False, refusal_reason=reason,
                     refusal_message=msg, alternatives=list(alts))


class RagPipeline:
    def __init__(self, retriever: Retriever, llm: LLM, *,
                 score_threshold: float = 0.3,
                 n_samples: int = 3,
                 consistency_threshold: float = 0.6,
                 grounding_threshold: float = 0.5,
                 consistency_fn: Optional[Callable[[Sequence[str]], bool]] = None):
        self.retriever = retriever
        self.llm = llm
        self.score_threshold = score_threshold
        self.n_samples = n_samples
        self.consistency_threshold = consistency_threshold
        self.grounding_threshold = grounding_threshold
        # 자기일관성 판정기. 미주입 시 lexical Jaccard(mock/기본). 실 임베딩 백엔드는
        # service에서 코사인 기반 판정기를 주입한다(한국어 표현 변주 오거부 완화).
        self.consistency_fn = consistency_fn

    def answer(self, query: str) -> RagResult:
        # 1) 의도 게이트
        bad = intent_gate(query)
        if bad is not None:
            return _refuse(bad)

        # 2) 검색 게이트
        docs = self.retriever.search(query)
        docs = [d for d in docs if d.score >= self.score_threshold]
        if not docs:
            return _refuse(RefusalReason.NO_EVIDENCE)

        # 3) 생성 + 자기일관성
        samples = [self.llm.generate(query, docs) for _ in range(self.n_samples)]
        consistent = (self.consistency_fn(samples) if self.consistency_fn
                      else self_consistency(samples, self.consistency_threshold))
        if not consistent:
            return replace(_refuse(RefusalReason.INCONSISTENT),
                           consistency_ok=False, sources=docs)

        answer = next((s for s in samples if s and s.strip()), "")

        # 3b) 부실 답변 가드 (너무 짧거나 반복 → lexical 게이트 우회 차단)
        if _is_degenerate(answer):
            return replace(_refuse(RefusalReason.NO_EVIDENCE),
                           consistency_ok=True, sources=docs)

        # 4) 근거율 게이트
        g = grounding_ratio(answer, [d.text for d in docs])
        if g < self.grounding_threshold:
            return replace(_refuse(RefusalReason.NO_EVIDENCE),
                           grounding=g, consistency_ok=True, sources=docs)

        return RagResult(
            answered=True, answer=answer, sources=docs,
            grounding=g, consistency_ok=True,
        )
