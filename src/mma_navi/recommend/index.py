"""특기 인덱스(특기 단위 집계) 기반 추천.

teukgi_index.json: { "특기명|군": {teukgi_code, teukgi_name, branch,
                                   certs:{명:등급}, licenses:{명:등급}, majors:[명]} }

매칭:
- 자격/면허: 결정론 이름 매칭(+점수내장 자격명 파싱) + 등급검증 → ok/unknown/grade.
  qualifies=True는 'ok'(검증충족)만. unknown은 verification_required로 분리(거짓충족 방지).
- 전공: 관련도(현재 lexical proxy; bge-m3 임베딩은 Phase 1).

성능: load_index에서 entry별 전공 토큰셋(_mtok)·자격통합(_quals) 전처리.
"""
from __future__ import annotations

import json
import re
from typing import List

from ..rag.gates import tokens
from .teukgi import (
    _STATUS_TIER,
    TeukgiMatch,
    TeukgiRule,
    UserProfile,
    _is_possession,
    _qual_match,
)

_VARIANT_PREFIX = re.compile(r"^\([^)]*\)\s*")   # 선두 (맞춤)/(임기제) 등

# UI/일상어 ↔ 공개데이터(3066750) 병과 라벨 불일치 정규화.
# 데이터는 '해병'이지만 사용자·UI는 '해병대'라 부른다 → 미정규화 시 선호군 필터가 전부 배제.
_BRANCH_ALIAS = {"해병대": "해병"}


def _norm_branch(b: str) -> str:
    return _BRANCH_ALIAS.get(b, b)


def load_index(path: str) -> dict:
    """JSON 로드 + entry별 토큰/자격 전처리(전체 majors 기준, 절단 없음)."""
    with open(path, encoding="utf-8") as f:
        index = json.load(f)
    for entry in index.values():
        _prepare(entry)
    return index


def _prepare(entry: dict) -> None:
    if "_mtok" in entry and "_quals" in entry:   # 둘 다 있어야 '완전 전처리'(부분/구버전 방어)
        return
    mtok = tokens(entry.get("teukgi_name", ""))
    for m in entry.get("majors", []):
        mtok |= tokens(m)
    entry["_mtok"] = mtok
    entry["_quals"] = {**entry.get("certs", {}), **entry.get("licenses", {})}


def _index_relevance(profile: UserProfile, entry: dict) -> float:
    left = tokens(" ".join([*profile.majors, *profile.interests, *profile.certificates]))
    if not left:
        return 0.0
    right = entry.get("_mtok")
    if right is None:
        _prepare(entry)
        right = entry["_mtok"]
    return round(len(left & right) / len(left), 3)


def _index_qualifies(profile: UserProfile, entry: dict):
    """반환 (status, matched, qual, grade). status: ok/unknown/grade/no_match."""
    quals = entry.get("_quals")
    if quals is None:
        _prepare(entry)
        quals = entry["_quals"]
    for holding in profile.all_holdings():
        if not _is_possession(holding):
            continue
        for qual, grade in quals.items():
            st = _qual_match(holding, qual, grade)
            if st != "none":
                return st, holding, qual, grade
    return "no_match", "", "", ""


def _base_name(name: str) -> str:
    return _VARIANT_PREFIX.sub("", name).strip()


def recommend_from_index(profile: UserProfile, index: dict, top_k: int = 5,
                         min_relevance: float = 0.05, dedup: bool = True,
                         sem_scores: dict = None) -> List[TeukgiMatch]:
    """sem_scores(key->bge 코사인)가 주어지면 lexical 대신 의미 관련도를 쓴다."""
    pref = {_norm_branch(b) for b in (profile.preferred_branches or [])}
    out: List[TeukgiMatch] = []
    for key, entry in index.items():
        if pref and _norm_branch(entry.get("branch")) not in pref:
            continue
        status, matched, qual, grade = _index_qualifies(profile, entry)
        rel = sem_scores.get(key, 0.0) if sem_scores is not None else _index_relevance(profile, entry)
        if status == "no_match" and rel < min_relevance:
            continue
        if status == "ok":
            reason = f"보유 자격/면허({matched})이 지원 요건과 일치" + (f" (요건: {grade})" if grade else "")
        elif status == "unknown":
            reason = f"보유({matched})가 요건 명칭과 일치 — 등급·요건({grade}) 본인 확인"
        elif status == "grade":
            reason = f"보유({matched})는 일치하나 등급·점수 요건({grade}) 미충족·확인 필요"
        else:
            reason = "전공·관심 관련성 — 지원 자격 요건 확인 필요"
        rule = TeukgiRule(
            teukgi_code=entry.get("teukgi_code", ""),
            teukgi_name=entry.get("teukgi_name", ""),
            branch=entry.get("branch", ""),
            qualification=qual,
            qual_type=("자격/면허" if qual else "전공"),
            grade_req=grade,
        )
        out.append(TeukgiMatch(
            rule=rule, qualifies=(status == "ok"), status=status,
            verification_required=(status == "unknown"),
            matched_on=matched, relevance=rel, reason=reason))
    out.sort(key=lambda m: (_STATUS_TIER.get(m.status, 0), m.relevance), reverse=True)

    if dedup:   # (맞춤)/(임기제) 변형은 base 특기명+군 기준 1개만(최상위 유지)
        seen, deduped = set(), []
        for m in out:
            k = (_base_name(m.rule.teukgi_name), m.rule.branch)
            if k in seen:
                continue
            seen.add(k)
            deduped.append(m)
        out = deduped
    return out[:top_k]
