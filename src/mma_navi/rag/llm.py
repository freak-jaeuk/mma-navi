"""로컬 LLM(Qwen) 생성기 — 근거 문맥만으로 답하는 grounded 생성기(LLM 프로토콜).

명세서 F1: bge-m3 검색 → 로컬 LLM 생성 + 거부 게이트. 본 모듈은 '생성' 부분.
시스템 프롬프트로 (1) 근거 내용만 사용 (2) 개인 신체등급/합격/면제 예측 금지를
강제한다. 환각 방지의 1차 방어이며, pipeline의 근거율·자기일관성 게이트가 2차 방어.
모델은 lazy 싱글톤. 오프라인 캐시 사용.
"""
from __future__ import annotations

import os
import threading
from typing import Sequence

from .pipeline import RetrievedDoc

MODEL_NAME = os.environ.get("MMA_LLM_MODEL", "Qwen/Qwen3-1.7B")

_SYS = (
    "너는 병무청 안내 도우미다. 반드시 아래 '근거'에 있는 내용만으로 한국어로 2문장 이내로 "
    "간결히 답하라. 근거에 없는 내용은 지어내지 말고 '제공된 자료로는 답할 수 없습니다'라고 "
    "답하라. 개인의 신체등급·합격·면제 여부는 절대 예측하지 마라."
)

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
        from transformers import AutoModelForCausalLM, AutoTokenizer
        # 디바이스를 로드 전에 결정: CUDA 실제 가용할 때만 GPU+bf16, 아니면 CPU+fp32
        want = os.environ.get("MMA_LLM_DEVICE", "cuda:0")
        use_cuda = want.startswith("cuda") and torch.cuda.is_available()
        dev = want if use_cuda else "cpu"
        dtype = torch.bfloat16 if use_cuda else torch.float32
        tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        if tok.pad_token_id is None and tok.eos_token is not None:
            tok.pad_token = tok.eos_token
        model = AutoModelForCausalLM.from_pretrained(MODEL_NAME, torch_dtype=dtype).eval()
        try:
            model = model.to(dev)
        except Exception:  # noqa: BLE001 — GPU 불가 시 CPU(fp32) 폴백
            dev = "cpu"
            model = model.float().to("cpu")
        _tok, _model, _device = tok, model, dev


def _build_prompt(query: str, contexts: Sequence[RetrievedDoc]) -> str:
    ctx = "\n".join(f"- {c.text}" for c in list(contexts)[:3]) or "(근거 없음)"
    msgs = [{"role": "system", "content": _SYS},
            {"role": "user", "content": f"근거:\n{ctx}\n\n질문: {query}"}]
    try:
        return _tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True,
                                        enable_thinking=False)
    except TypeError:  # enable_thinking 미지원 모델
        return _tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True)


class LocalLLM:
    """Qwen 계열 instruct 모델로 grounded 답변 생성."""

    def __init__(self, max_new_tokens: int = 140, temperature: float = 0.3):
        self.max_new_tokens = max_new_tokens
        self.temperature = temperature

    def load(self) -> None:
        """모델을 지금 로드(첫 generate가 아니라 팩토리에서 실패를 잡게)."""
        _load()

    def generate(self, query: str, contexts: Sequence[RetrievedDoc]) -> str:
        _load()
        import torch
        text = _build_prompt(query, contexts)
        inp = _tok(text, return_tensors="pt")
        if _device != "cpu":
            inp = {k: v.to(_device) for k, v in inp.items()}
        pad_id = (_tok.pad_token_id or _tok.eos_token_id
                  or getattr(_model.config, "eos_token_id", None))
        with torch.no_grad():
            out = _model.generate(
                **inp, max_new_tokens=self.max_new_tokens,
                do_sample=self.temperature > 0, temperature=max(self.temperature, 1e-2),
                top_p=0.8, pad_token_id=pad_id)
        n_in = inp["input_ids"].shape[1]
        text = _tok.decode(out[0][n_in:], skip_special_tokens=True).strip()
        # 프롬프트의 불릿/머리기호가 새어나오면 제거
        return text.lstrip("-•· \t").strip()


def is_available() -> bool:
    try:
        _load()
        return True
    except Exception:  # noqa: BLE001
        return False
