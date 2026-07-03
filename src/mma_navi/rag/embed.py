"""bge-m3 임베딩 — transformers로 직접 로드(sentence-transformers 의존 없음).

bge-m3 dense embedding = last_hidden_state[:,0](CLS 토큰) → L2 정규화.
소규모 KB는 CPU에서도 충분히 빠르다(16건 ≈ 0.6s). 모델은 lazy 싱글톤.
오프라인 캐시 사용(HF_HUB_OFFLINE) — 네트워크 불필요.
"""
from __future__ import annotations

import os
import threading
from typing import Sequence

import numpy as np

MODEL_NAME = os.environ.get("MMA_EMBED_MODEL", "BAAI/bge-m3")
EMBED_DIM = 1024

_lock = threading.Lock()
_tok = None
_model = None
_device = "cpu"


def _load() -> None:
    global _tok, _model, _device
    if _model is not None:
        return
    with _lock:
        if _model is not None:
            return
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        import torch
        from transformers import AutoModel, AutoTokenizer
        dev = os.environ.get("MMA_EMBED_DEVICE", "cpu")
        tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        model = AutoModel.from_pretrained(MODEL_NAME).eval()
        if dev != "cpu":
            try:
                model = model.to(dev)
            except Exception:  # noqa: BLE001 — GPU 불가 시 CPU 유지
                dev = "cpu"
        _tok, _model, _device = tok, model, dev


def embed(texts: Sequence[str], batch_size: int = 16) -> np.ndarray:
    """텍스트들을 bge-m3 dense 벡터(정규화)로 인코딩. (N, 1024) float32."""
    _load()
    import torch
    texts = list(texts)
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype="float32")
    out = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        inp = _tok(batch, padding=True, truncation=True, max_length=512, return_tensors="pt")
        if _device != "cpu":
            inp = {k: v.to(_device) for k, v in inp.items()}
        with torch.no_grad():
            vec = _model(**inp).last_hidden_state[:, 0]
            vec = torch.nn.functional.normalize(vec, p=2, dim=1)
        out.append(vec.cpu().numpy().astype("float32"))
    return np.vstack(out)


def device() -> str:
    _load()
    return _device


def is_available() -> bool:
    try:
        _load()
        return True
    except Exception:  # noqa: BLE001
        return False
