"""특기 의미 관련도 — bge-m3 임베딩으로 전공·관심사 ↔ 특기 매칭(lexical proxy 대체).

기존 _index_relevance(토큰 겹침)는 '보안 관심 → 포병' 같은 오매칭을 낸다.
494개 특기를 대표 텍스트로 1회 임베딩해 두고, 프로필을 임베딩해 코사인으로 관련도를 준다.
bge-m3 미가용 시에는 호출부가 lexical로 폴백한다.

캐시 정합성(중요): 키만이 아니라 (스키마버전 + 모델명 + dim + 모든 특기 대표텍스트)의
지문(fingerprint)을 함께 저장·검증한다. 특기 내용이나 임베딩 모델이 바뀌면 stale 캐시를
재사용하지 않고 재계산한다. 저장은 임시파일 → os.replace로 원자 교체.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Dict, List, Optional

import numpy as np

_CACHE = os.path.join(os.path.dirname(__file__), "..", "..", "..",
                      "data", "cache", "teukgi_emb.npz")
_SCHEMA = "v2"
EMBED_DIM = 1024


def _entry_text(entry: dict) -> str:
    """특기 대표 텍스트(특기명 + 군 + 전공 + 자격명)."""
    parts = [entry.get("teukgi_name", ""), entry.get("branch", "")]
    parts += list(entry.get("majors", []))[:10]
    quals = {**entry.get("certs", {}), **entry.get("licenses", {})}
    parts += list(quals.keys())[:10]
    return " ".join(p for p in parts if p)


def _fingerprint(texts: List[str]) -> str:
    """캐시 정합성 지문: 스키마·모델·dim·전체 대표텍스트 내용 해시."""
    from ..rag.embed import MODEL_NAME
    h = hashlib.sha256()
    for part in (_SCHEMA, MODEL_NAME, str(EMBED_DIM)):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    for t in texts:
        h.update(t.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


class TeukgiSemanticIndex:
    """494 특기 임베딩 사전계산 + 프로필 코사인 관련도."""

    def __init__(self, index: dict, cache_path: Optional[str] = _CACHE):
        self.keys = list(index.keys())
        texts = [_entry_text(index[k]) for k in self.keys]
        fp = _fingerprint(texts)
        cached = self._load_cache(cache_path, fp)
        if cached is not None:
            self.emb = cached
        else:
            from ..rag.embed import embed
            self.emb = embed(texts) if texts else np.zeros((0, EMBED_DIM), dtype="float32")
            self._save_cache(cache_path, fp)

    def _load_cache(self, path: Optional[str], fp: str) -> Optional[np.ndarray]:
        """지문·키가 모두 일치할 때만 캐시 임베딩 재사용(stale 방지)."""
        if not path or not os.path.exists(path):
            return None
        try:
            d = np.load(path, allow_pickle=False)
            emb = d["emb"]
            if (str(d["fingerprint"]) == fp
                    and list(map(str, d["keys"])) == self.keys
                    and emb.ndim == 2 and emb.shape == (len(self.keys), EMBED_DIM)):
                return emb
        except Exception:  # noqa: BLE001 — 캐시 손상/구버전 시 재계산
            pass
        return None

    def _save_cache(self, path: Optional[str], fp: str) -> None:
        if not path:
            return
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".npz")
            try:
                with os.fdopen(fd, "wb") as f:        # 파일객체 → np.savez가 확장자 안 붙임
                    np.savez(f, keys=np.array(self.keys), emb=self.emb,
                             fingerprint=np.array(fp))   # 모두 string/float dtype(pickle 불필요)
                os.replace(tmp, path)                 # 원자 교체(동시쓰기 깨짐 방지)
            except Exception:
                if os.path.exists(tmp):
                    os.remove(tmp)
                raise
        except Exception:  # noqa: BLE001
            pass

    def scores(self, query_text: str) -> Dict[str, float]:
        """프로필 텍스트 대비 각 특기의 코사인 관련도 {key: score}."""
        q = (query_text or "").strip()
        if not q or self.emb.shape[0] == 0:
            return {}
        from ..rag.embed import embed
        qv = embed([q])[0]
        sims = self.emb @ qv
        return {k: round(float(s), 3) for k, s in zip(self.keys, sims)}
