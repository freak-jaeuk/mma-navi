"""모집병 특기 추천 — 자격충족(결정론) + 의미관련도(랭킹) 분리.

명세서 §F2 + Codex 권고: '추천 정확도'를 하나로 뭉뚱그리지 않는다.
- 자격 충족: 공개 자격요건(3066750) 대비 결정론 매칭 = 검증가능('정확').
- 의미 관련도: 전공·관심사 ↔ 특기/자격 임베딩(여기선 lexical proxy) = '관련도'.
- 금지: "무조건 합격" 류 표현. "지원 자격 검토 가능"까지만.

데이터(3066750) 필드:
  gsteukgiCd 군사특기코드 / gsteukgiNm 군사특기명 / gtcdNm1 군명 /
  gtcdNm2 자격면허전공명 / gubun 자격면허전공구분 / jgmyeonheoDg 자격면허등급 /
  jjganjeopGbcd 직간접구분
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

from ..rag.gates import jaccard, tokens


@dataclass(frozen=True)
class TeukgiRule:
    teukgi_code: str
    teukgi_name: str        # gsteukgiNm
    branch: str             # gtcdNm1 (군)
    qualification: str      # gtcdNm2 (자격면허전공명)
    qual_type: str = ""     # gubun (자격/면허/전공)
    grade_req: str = ""     # jgmyeonheoDg (예: 기사급이상)
    direct_indirect: str = ""


@dataclass
class UserProfile:
    majors: List[str] = field(default_factory=list)
    certificates: List[str] = field(default_factory=list)
    interests: List[str] = field(default_factory=list)
    preferred_branches: List[str] = field(default_factory=list)

    def all_holdings(self) -> List[str]:
        return [*self.majors, *self.certificates]


@dataclass(frozen=True)
class TeukgiMatch:
    rule: TeukgiRule
    qualifies: bool          # 검증된 자격충족(status=='ok')만 True
    status: str              # 'ok' | 'unknown'(이름일치·등급미확인) | 'grade'(미달) | 'no_match'
    verification_required: bool  # status=='unknown' (본인 확인 필요)
    matched_on: str          # 무엇으로 매칭했는지(자격증/전공명) 또는 ""
    relevance: float         # 의미 관련도 0~1
    reason: str              # 사용자 표시 사유(합격 표현 금지)


# 자격 등급 랭크 (긴 키워드 먼저: '산업기사'를 '기사'보다 먼저 매칭)
_GRADE_KW = [("기술사", 5), ("기능장", 4), ("산업기사", 2), ("기능사", 1), ("기사", 3)]


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "").lower()


def _infer_grade_rank(name: str) -> Optional[int]:
    n = _norm(name)
    for kw, rank in _GRADE_KW:
        if kw in n:
            return rank
    return None


# 비보유(희망/준비) 표현 — 자격 '보유'로 처리하면 안 됨
_ASPIRATIONAL = ("준비", "목표", "예정", "공부", "따려", "딸", "취득예정", "준비중")


def _is_possession(holding: str) -> bool:
    return bool(holding) and not any(w in holding for w in _ASPIRATIONAL)


def _grade_check(holding: str, grade_req: str) -> str:
    """등급/점수 요건 결과: 'ok'(충족/요건없음) / 'grade'(미충족 확인) / 'unknown'(검증불가).

    반환값은 상위 계약(`_qual_match`/`_qualifies`/`_STATUS_TIER`/사유 메시지)이 쓰는
    상태어와 통일한다 — 미달은 반드시 'grade'다('fail'을 반환하면 소비부의 grade 분기·
    tier에 매칭되지 않아 등급미달자가 '관련성' 후보로 조용히 오표기됨).
    해석 불가(예: '일반면허공인')나 보유 등급 불명은 'unknown' — 이름매칭으로 후보로 두되
    등급은 '본인 확인'으로 표기(과도한 누락 방지). 점수/등급이 명확히 미달하면 'grade'.
    """
    req = (grade_req or "").strip()
    if not req:
        return "ok"
    m = re.search(r"(\d{2,4})\s*점?\s*이상", req)
    if m:
        hm = re.search(r"(\d{2,4})", holding)
        if not hm:
            return "unknown"
        return "ok" if int(hm.group(1)) >= int(m.group(1)) else "grade"
    req_rank = _infer_grade_rank(req)
    if req_rank is None:
        return "unknown"
    hold_rank = _infer_grade_rank(holding)
    if hold_rank is None:
        return "unknown"
    return "ok" if hold_rank >= req_rank else "grade"


def _name_match(holding: str, qualification: str) -> bool:
    """보유 항목이 자격/전공 '전체 명칭'을 포함하는지(부분토큰 거짓충족 방지)."""
    h, q = _norm(holding), _norm(qualification)
    return bool(q) and (q == h or q in h)


def _parse_qual(qualification: str) -> tuple:
    """자격명에 점수가 내장된 경우 (base_name, min_score) 추출. 없으면 (원문, None).

    예: '토익 900점이상자(접수종료 기준 2년이내)' → ('토익', 900)
    """
    m = re.search(r"(\d{3,4})\s*점", qualification or "")
    if m:
        base = (qualification[:m.start()]).strip(" .·,/()")
        return (base or qualification), int(m.group(1))
    return qualification, None


def _qual_match(holding: str, qualification: str, grade_req: str) -> str:
    """자격명(점수내장 포함)+등급 검증. 'ok'|'unknown'|'grade'(미달)|'none'(이름불일치)."""
    base, embed_score = _parse_qual(qualification)
    if not _name_match(holding, base):
        return "none"
    if embed_score is not None:
        hm = re.search(r"(\d{3,4})", holding)
        if not hm:
            return "unknown"
        return "ok" if int(hm.group(1)) >= embed_score else "grade"
    return _grade_check(holding, grade_req)


def _qualifies(profile: UserProfile, rule: TeukgiRule) -> tuple:
    """반환 (status, matched_holding). status: 'ok'|'unknown'|'grade'|'no_match'."""
    for holding in profile.all_holdings():
        if not _is_possession(holding):
            continue
        st = _qual_match(holding, rule.qualification, rule.grade_req)
        if st != "none":
            return st, holding
    return "no_match", ""


def _relevance(profile: UserProfile, rule: TeukgiRule) -> float:
    """전공+관심사 ↔ 특기명+자격명 의미 관련도(lexical proxy)."""
    left = " ".join([*profile.majors, *profile.interests, *profile.certificates])
    right = f"{rule.teukgi_name} {rule.qualification}"
    return round(jaccard(left, right), 3)


def recommend(profile: UserProfile, rules: Sequence[TeukgiRule],
              top_k: int = 5, min_relevance: float = 0.0) -> List[TeukgiMatch]:
    """자격충족 우선, 그다음 관련도 순으로 특기 추천."""
    pref = {b for b in (profile.preferred_branches or [])}
    matches: List[TeukgiMatch] = []
    for rule in rules:
        if pref and rule.branch not in pref:
            continue
        status, matched = _qualifies(profile, rule)
        rel = _relevance(profile, rule)
        if status == "no_match" and rel < min_relevance:
            continue
        grade = f" (요건: {rule.grade_req})" if rule.grade_req else ""
        if status == "ok":
            reason = f"보유 {rule.qual_type or '자격/전공'}({matched})이 지원 요건과 일치{grade}"
        elif status == "unknown":
            reason = f"보유({matched})가 요건 명칭과 일치 — 등급·요건({rule.grade_req}) 본인 확인"
        elif status == "grade":
            reason = f"보유({matched})는 일치하나 등급·점수 요건({rule.grade_req}) 미충족·확인 필요"
        else:
            reason = f"전공·관심 관련성 높음 — 지원 요건({rule.qualification}{grade}) 확인 필요"
        matches.append(TeukgiMatch(
            rule=rule, qualifies=(status == "ok"), status=status,
            verification_required=(status == "unknown"),
            matched_on=matched, relevance=rel, reason=reason))
    # 검증충족(ok) > 본인확인(unknown) > 등급미달/관련도 순, 그 안에서 관련도
    matches.sort(key=lambda m: (_STATUS_TIER.get(m.status, 0), m.relevance), reverse=True)
    return matches[:top_k]


_STATUS_TIER = {"ok": 3, "unknown": 2, "grade": 1, "no_match": 0}
