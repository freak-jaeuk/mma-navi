"""bge-m3 dense retriever — MockRetriever(토큰 겹침)를 대체하는 실 의미검색.

한국어 조사/어미로 인한 토큰 미스매치 문제를 임베딩 유사도로 해결한다.
KB 임베딩은 생성 시 1회 precompute. 검색은 코사인(정규화 → 내적).
선택적으로 bge-reranker-v2-m3로 상위 후보 재정렬(MMA_RERANK=1).
"""
from __future__ import annotations

import os
import threading
from typing import List, Sequence, Tuple

import numpy as np

from .embed import embed
from .pipeline import RetrievedDoc

_rr_lock = threading.Lock()
_rr_tok = None
_rr_model = None
_rr_device = "cpu"


def _load_reranker():
    """bge-reranker-v2-m3 lazy 로드(점수: 쌍 분류 logit)."""
    global _rr_tok, _rr_model, _rr_device
    if _rr_model is not None:
        return
    with _rr_lock:
        if _rr_model is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        name = os.environ.get("MMA_RERANK_MODEL", "BAAI/bge-reranker-v2-m3")
        dev = os.environ.get("MMA_EMBED_DEVICE", "cpu")
        tok = AutoTokenizer.from_pretrained(name)
        model = AutoModelForSequenceClassification.from_pretrained(name).eval()
        if dev != "cpu":
            try:
                model = model.to(dev)
            except Exception:  # noqa: BLE001
                dev = "cpu"
        _rr_tok, _rr_model, _rr_device = tok, model, dev


def _rerank(query: str, docs: List[RetrievedDoc]) -> List[RetrievedDoc]:
    _load_reranker()
    import torch
    pairs = [[query, d.text] for d in docs]
    inp = _rr_tok(pairs, padding=True, truncation=True, max_length=512, return_tensors="pt")
    if _rr_device != "cpu":
        inp = {k: v.to(_rr_device) for k, v in inp.items()}
    with torch.no_grad():
        scores = _rr_model(**inp).logits.view(-1).float()
        scores = torch.sigmoid(scores).cpu().numpy()
    ranked = sorted(zip(docs, scores), key=lambda x: x[1], reverse=True)
    return [RetrievedDoc(text=d.text, source=d.source, score=round(float(s), 3))
            for d, s in ranked]


class BgeRetriever:
    """bge-m3 임베딩 기반 dense 검색기(Retriever 프로토콜)."""

    def __init__(self, kb: Sequence[Tuple[str, str]], use_reranker: bool = False):
        self.kb = list(kb)
        self.use_reranker = use_reranker or os.environ.get("MMA_RERANK") == "1"
        texts = [t for t, _ in self.kb]
        self._emb = embed(texts) if texts else np.zeros((0, 1), dtype="float32")
        if self.use_reranker:
            _load_reranker()   # eager: 로드 실패를 팩토리 try에서 잡음(lazy 폴백 구멍 방지)

    def search(self, query: str, k: int = 5) -> List[RetrievedDoc]:
        if not self.kb:
            return []
        q = embed([query])[0]
        sims = self._emb @ q                       # 정규화 → 코사인 유사도
        # reranker 쓰면 더 넓게 뽑아 재정렬
        pool = min(len(self.kb), max(k, 10) if self.use_reranker else k)
        order = np.argsort(-sims)[:pool]
        docs = [RetrievedDoc(text=self.kb[i][0], source=self.kb[i][1],
                             score=round(float(sims[i]), 3)) for i in order]
        if self.use_reranker and docs:
            try:
                docs = _rerank(query, docs)
            except Exception:  # noqa: BLE001 — reranker 실패 시 dense 결과로 degrade
                pass
        return docs[:k]
