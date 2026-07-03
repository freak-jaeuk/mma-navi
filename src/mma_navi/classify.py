"""민원 질문 분류기 (F5) — 신검/모집병/사회복무/여비/진로 5범주.

현재는 키워드 argmax(설명가능·결정론). 임베딩 분류는 Phase 1. 정확도는 분류 평가셋으로
macro-F1 측정(AI30 증거).
"""
from __future__ import annotations

from typing import Dict, Tuple

CATEGORIES = ["신검", "모집병", "사회복무", "여비", "진로"]

CATEGORY_KEYWORDS: Dict[str, list] = {
    "신검": ["신체검사", "신검", "병역판정검사", "판정검사", "신체등급", "bmi", "비만",
             "신장", "몸무게", "체중", "시력", "혈압", "혈액", "백분위", "검사장", "검사일"],
    "모집병": ["모집병", "특기", "군특기", "지원자격", "자격증", "전공", "경쟁률",
               "접수", "기술병", "모집", "지원"],
    "사회복무": ["사회복무", "복무기관", "소집", "공익근무", "복무지", "근무지", "복무"],
    "여비": ["여비", "교통비", "비용", "지급", "식비", "숙박", "정산", "보상금"],
    "진로": ["진로", "상담", "설계지원센터", "진로설계", "센터", "컨설팅", "취업연계"],
}

UNKNOWN = "미상"


def classify(text: str) -> Tuple[str, Dict[str, int]]:
    """질문을 5범주 중 하나로 분류. 키워드 미적중이면 '미상'. (category, 점수)."""
    t = (text or "").lower()
    scores = {c: sum(1 for kw in kws if kw.lower() in t)
              for c, kws in CATEGORY_KEYWORDS.items()}
    best = max(CATEGORIES, key=lambda c: scores[c])  # 동점 시 CATEGORIES 순서 우선
    if scores[best] == 0:
        return UNKNOWN, scores
    return best, scores
