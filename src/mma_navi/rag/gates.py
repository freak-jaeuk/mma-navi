"""거부 게이트(Refusal Gates) — '거부할 줄 아는 AI'의 핵심 로직.

명세서 §F1/§4: 근거가 없거나 개인 판정이 필요한 질문은 답하지 않고 거부한다.
거부 taxonomy(통일): 개인판정 / 의료진단 / 합격·면제예측 / 근거부족 (+내부: 불확실).

설계 원칙:
- 의도 게이트(intent)는 규칙 기반(한국어 패턴). 휴리스틱이며 정확도는 Phase 0-4의
  거부 평가셋으로 precision/recall 측정·튜닝한다(여기 패턴은 출발점).
- 근거/일관성 게이트는 lexical proxy(토큰 겹침). NLI 고도화는 추후(명세 명시).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Sequence


class RefusalReason(str, Enum):
    INDIVIDUAL_JUDGMENT = "개인판정"      # 개인 신체등급/병역처분 판단 요구
    MEDICAL_DIAGNOSIS = "의료진단"        # 질병명/의학적 진단 요구
    PASS_PREDICTION = "합격예측"          # 미래 합격/면제 예측 요구
    NO_EVIDENCE = "근거부족"              # 공개자료에서 근거 못 찾음
    INCONSISTENT = "불확실"               # 자기일관성 미달(내부 게이트)


# 거부 유형별 사용자 메시지 + 대신 제공 가능 정보(거부=막힘이 아니라 안내)
REFUSAL_MESSAGES = {
    RefusalReason.INDIVIDUAL_JUDGMENT: (
        "공개자료만으로 개인의 병역처분을 판단할 수 없습니다.",
        ["BMI·신장 백분위", "병역판정검사 절차 안내", "병무청 상담 연결"],
    ),
    RefusalReason.MEDICAL_DIAGNOSIS: (
        "질병명 또는 의학적 진단은 의료진 판단이 필요합니다.",
        ["병역판정검사 절차 안내", "의료기관·보건소 상담 안내"],
    ),
    RefusalReason.PASS_PREDICTION: (
        "미래 합격 여부나 면제 가능성은 공개자료로 예측할 수 없습니다.",
        ["지원 자격 요건", "현재 회차 경쟁률 조회", "모집병 특기 정보"],
    ),
    RefusalReason.NO_EVIDENCE: (
        "현재 확보된 병무청 공개자료에서 근거를 찾지 못했습니다.",
        ["병무청 공식 누리집·상담 안내"],
    ),
    RefusalReason.INCONSISTENT: (
        "답변의 일관성이 확인되지 않아 안내를 제공하지 않습니다.",
        ["병무청 공식 누리집·상담 안내"],
    ),
}


# --- 의도 게이트 패턴 (한국어, 순서: 의료 → 개인판정 → 합격예측) ---
# 한국어는 \b가 조사/어미 앞에서 신뢰할 수 없어 사용하지 않는다.
# '위험 대상어 + 판단/예측 동사' 조합으로 넓게 잡되, 절차/안내(준비·절차·어디·언제)는
# 동사로 넣지 않아 false positive를 피한다. 정밀 튜닝은 Phase 0-4 거부 평가셋으로.

# 대상어: 짧은 동사 substring 오탐(예: '병가나'의 '가나') 방지 위해 동사는 긴 형태만.
# 입영/입대는 절차질문(여비·일정)에 흔해 FP유발 → target에서 제외(회피패턴엔 별도 유지)
_OUTCOME_TARGET = r"(현역|보충역|사회복무요원|공익|면제|재검|[1-7]\s*급)"
_OUTCOME_VERB = (r"(갈까|갈래|가나요|가도\s*되|될까|될까요|되나요|되냐|되겠|가능|예측|"
                 r"받을까|받을\s*수|받을지|나올까|나와요|일까|할까|있을까|있을지|"
                 r"봐\s*줘|판정\s*해|맞춰|뽑아\s*줘)")
_INDIVIDUAL = [
    rf"{_OUTCOME_TARGET}.{{0,12}}{_OUTCOME_VERB}",
    rf"{_OUTCOME_VERB}.{{0,12}}{_OUTCOME_TARGET}",
    r"(안\s*갈|안\s*가|빠질|빠지|뺄|면제\s*받).{0,8}(수\s*있|가능|방법|될까|되나)",
    r"(나|저|제)\s*(는|가)?.{0,10}(현역|공익|보충역|면제|몇\s*급)",
    # 슬랭/완곡 (면제각/현역각)
    r"(면제|현역|공익|보충역)\s*각",
    # 개인 등급/처분 결과 요구 (절차질문 FP 방지 — '어떻게/기준/되나요'는 결과동사 필수)
    r"(병역\s*처분|신체\s*등급).{0,5}(예측|알려\s*줘|나오|나와|나옴|받|뭐|무엇|판정\s*해|맞춰)",
    r"(무슨|어떤|몇)\s*(등급|급|처분).{0,4}(받|나오|나와|나옴|될)",
    r"(등급|처분).{0,5}(어떻게|어케|어찌).{0,4}(나오|나와|나옴|받)",
    # 현역/보충역 선택 요구
    r"(현역|보충역|공익).{0,8}(어느\s*쪽|어디로|골라|맞을까|맞나)",
    # 군대 회피
    r"(군대|입영|입대|현역).{0,6}(안\s*가|안\s*감|빠지|면제|가도\s*되)",
]
_PASS = [
    r"(합격|불합격|붙|떨어|선발|뽑|당첨).{0,8}"
    r"(할까|될까|되나|가능|확률|수\s*있|수\s*없|나요|싶|어\?|을까|같아|것\s*같)",
    r"면제.{0,8}(가능|될까|확률|되나)",
    r"통과\s*(할|될|되|가능|하나|할\s*수)",
]
_MEDICAL_TERMS = (r"디스크|십자인대|인대|파열|부정맥|평발|고도근시|결절종|천식|탈구|"
                  r"공황장애|우울증|불안장애|정신과|간수치|간질환|종양|결핵|질환|질병|골절|증상")
_MEDICAL = [
    r"무슨\s*병", r"어떤\s*병", r"병\s*명", r"진단",
    r"다른\s*병",
    rf"({_MEDICAL_TERMS}).{{0,10}}"
    r"(인가요|인지|일까요|맞는지|맞나요|맞을까|아닌가요|판단|봐주|진단|되나|면제)",
    r"(정신과|우울증|불안장애|디스크|허리|무릎).{0,6}(다니|있는데|아픈|앓)",
]


def _matches(patterns: Sequence[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def intent_gate(query: str) -> Optional[RefusalReason]:
    """질문 의도가 거부 대상이면 사유 반환, 아니면 None."""
    q = query.strip()
    if _matches(_MEDICAL, q):
        return RefusalReason.MEDICAL_DIAGNOSIS
    if _matches(_INDIVIDUAL, q):
        return RefusalReason.INDIVIDUAL_JUDGMENT
    if _matches(_PASS, q):
        return RefusalReason.PASS_PREDICTION
    return None


def token_list(text: str) -> list:
    """2자 이상 토큰 리스트(중복 포함) — 반복/길이 검사용."""
    return [w.lower() for w in re.findall(r"[가-힣A-Za-z0-9]+", text or "") if len(w) >= 2]


# --- lexical proxy: 토큰화/겹침 (일관성·근거 게이트용) ---
def tokens(text: str) -> set:
    """2자 이상 한글/영숫자 토큰 집합."""
    raw = re.findall(r"[가-힣A-Za-z0-9]+", text or "")
    out = set()
    for w in raw:
        if len(w) >= 2:
            out.add(w.lower())
    return out


def jaccard(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def self_consistency(answers: Sequence[str], threshold: float = 0.6) -> bool:
    """N개 샘플 답변의 평균 쌍별 Jaccard가 임계 이상이면 일관(lexical proxy)."""
    answers = [a for a in answers if a and a.strip()]
    if len(answers) <= 1:
        return True
    sims, n = [], len(answers)
    for i in range(n):
        for j in range(i + 1, n):
            sims.append(jaccard(answers[i], answers[j]))
    return (sum(sims) / len(sims)) >= threshold if sims else True


def semantic_consistency(answers: Sequence[str], embed_fn,
                         threshold: float = 0.8,
                         lexical_fallback_threshold: float = 0.45) -> bool:
    """N개 샘플 답변의 평균 쌍별 코사인 유사도가 임계 이상이면 일관.

    Jaccard(토큰 겹침)는 조사/어미만 바뀐 같은 뜻 답변을 '불일치'로 오판해 답변을
    보수적으로 거부시킨다. 임베딩 코사인은 이런 표현 변주에 강건하다.
    embed_fn은 문자열 목록 → (N, D) 벡터를 주는 인코더(bge-m3). 인코딩이 실패하거나
    shape가 어긋나면 lexical self_consistency로 폴백한다(데모가 죽지 않게, 안전 우선).
    """
    cleaned = [a for a in answers if a and a.strip()]
    if len(cleaned) <= 1:
        return True
    try:
        import numpy as np
        emb = np.asarray(embed_fn(cleaned), dtype="float32")
        if emb.ndim != 2 or emb.shape[0] != len(cleaned) or emb.shape[1] == 0:
            raise ValueError("임베딩 shape 불일치")
        if not np.isfinite(emb).all():
            raise ValueError("임베딩에 NaN/Inf 포함")     # 유사도 계산 불능 → lexical 폴백
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        if not (norms > 1e-8).all():
            raise ValueError("0에 가까운 임베딩 벡터")     # 코사인 정의 불가 → lexical 폴백
        emb = emb / norms                        # 코사인 = 정규화 내적(중복 정규화는 무해)
        sims = np.clip(emb @ emb.T, -1.0, 1.0)   # 수치오차로 |cos|>1 방지
        iu = np.triu_indices(len(cleaned), k=1)  # 쌍별(대각 제외) 평균
        return float(sims[iu].mean()) >= threshold
    except Exception:  # noqa: BLE001 — 인코딩 실패/부적합 임베딩 시 lexical 폴백(안전 우선)
        return self_consistency(cleaned, lexical_fallback_threshold)


def grounding_ratio(answer: str, contexts: Sequence[str]) -> float:
    """답변 토큰 중 근거 문맥에 등장하는 비율(=근거율 proxy)."""
    at = tokens(answer)
    if not at:
        return 0.0
    ctx = set()
    for c in contexts:
        ctx |= tokens(c)
    return len(at & ctx) / len(at)
