"""서비스 레이어 — 4개 코어를 순수 함수로 래핑(라우트와 분리해 테스트 용이).

무거운 리소스(분포 테이블/특기 인덱스/RAG)는 lazy 싱글톤으로 1회만 로드한다.
모든 함수는 JSON 직렬화 가능한 dict/list만 반환한다(웹/테스트 공용).
"""
from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from typing import Dict, List, Optional

from ..dataio import load_distributions_csv
from ..mma_api import compute_bmi
from ..percentile import DistributionTable
from ..rag.mocks import MockLLM, MockRetriever
from ..rag.pipeline import RagPipeline, RagResult
from ..classify import classify as _classify
from ..recommend.index import load_index, recommend_from_index
from ..recommend.teukgi import UserProfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DATA = os.path.join(ROOT, "data")
EVAL = os.path.join(ROOT, "eval")

DIST_REAL = os.path.join(DATA, "distributions_real.csv")
DIST_FIXTURE = os.path.join(DATA, "fixtures", "distributions_sample.csv")
TEUKGI_INDEX = os.path.join(DATA, "teukgi_index.json")
BMGG_INDEX = os.path.join(DATA, "bmgg_by_region.json")   # 사회복무 복무기관(3066757) 지방청별
SOJIP_PLAN = os.path.join(DATA, "sojip_plan.json")       # 사회복무 소집계획(3066753) 분야별 집계
JEOPSU_RATE = os.path.join(DATA, "jeopsu_rate.json")     # 모집병 접수현황(15031295) 특기별 경쟁률
GONGSEOK_INDEX = os.path.join(DATA, "gongseok_by_region.json")  # 사회복무 본인선택 공석(3066754) 지방청별
JINRO_CENTERS = os.path.join(DATA, "jinro_centers.json")   # 병역진로설계센터 위치(15148370) 지방청별
KB_DEMO = os.path.join(DATA, "kb_demo.json")
REPORT = os.path.join(EVAL, "report.json")

DEFAULT_COHORT = "2026_전국"
_METRIC_LABEL = {"bmi": "BMI", "height": "신장", "weight": "체중"}
_METRIC_UNIT = {"bmi": "", "height": "cm", "weight": "kg"}

# RAG 백엔드: mock(기본·빠름) | bge-extractive(실 bge-m3 검색+추출) | bge-llm(+로컬 LLM 생성)
RAG_BACKEND = os.environ.get("MMA_RAG", "mock").lower()
_BGE_THRESHOLD = float(os.environ.get("MMA_BGE_THRESHOLD", "0.45"))
# 생성형 자기일관성 코사인 임계(bge 임베딩). 짧은 한국어 답변 패러프레이즈는 코사인이
# 높게(≈0.85+) 나오므로 0.8을 기본으로 둔다. lexical Jaccard보다 표현 변주에 강건.
_CONSISTENCY_COS = float(os.environ.get("MMA_CONSISTENCY_COS", "0.8"))

logger = logging.getLogger("mma_navi")

_lock = threading.Lock()          # tables/index 공용
_rag_lock = threading.Lock()      # RAG 전용(무거운 모델 로딩이 다른 로더를 막지 않게)
_tables: Optional[Dict[tuple, DistributionTable]] = None
_dist_source: str = ""
_index: Optional[dict] = None
_rag: Optional[RagPipeline] = None
_rag_backend: str = ""            # 실제 활성화된 백엔드(폴백 반영)
_sem_lock = threading.Lock()      # 특기 의미인덱스 전용
_sem_index = None                 # TeukgiSemanticIndex | False(빌드 실패)

# 특기 의미매칭(bge-m3) 사용 여부 — bge RAG 백엔드거나 명시 활성화 시
_USE_SEM_TEUKGI = (RAG_BACKEND in ("bge", "bge-extractive", "bge-llm")
                   or os.environ.get("MMA_TEUKGI_SEM") == "1")
# bge-m3 코사인 관련도 임시 컷오프(무관 특기 제외). 평가셋 튜닝 전 휴리스틱 — env로 조정.
_SEM_MIN_REL = float(os.environ.get("MMA_TEUKGI_MIN_REL", "0.4"))


# --- lazy 로더 (스레드 안전) -------------------------------------------------
def _get_tables() -> Dict[tuple, DistributionTable]:
    global _tables, _dist_source
    if _tables is None:
        with _lock:
            if _tables is None:
                if os.path.exists(DIST_REAL):
                    tables, source = load_distributions_csv(DIST_REAL), "real"
                else:
                    tables, source = load_distributions_csv(DIST_FIXTURE), "fixture"
                _dist_source = source   # _tables를 마지막에 publish(상태 일관)
                _tables = tables
    return _tables


def _get_index() -> dict:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                if not os.path.exists(TEUKGI_INDEX):
                    _index = {}
                else:
                    # load_index가 lock 안에서 모든 entry의 _mtok/_quals를 미리 전처리한다.
                    # (요청 중 lazy 변형 시 동시성 레이스로 KeyError가 날 수 있어 차단 — Codex 중대)
                    _index = load_index(TEUKGI_INDEX)
    return _index


def _load_kb() -> list:
    if os.path.exists(KB_DEMO):
        with open(KB_DEMO, encoding="utf-8") as f:
            return [(d["text"], d["source"]) for d in json.load(f)]
    return []


def _build_rag(kb: list) -> RagPipeline:
    """MMA_RAG 백엔드에 따라 RAG 파이프라인 구성. 실패 시 mock 폴백(데모는 떠야 함)."""
    global _rag_backend
    backend = RAG_BACKEND
    if backend in ("bge", "bge-extractive", "bge-llm"):
        try:
            from ..rag.retriever import BgeRetriever
            retriever = BgeRetriever(kb)
            if backend == "bge-extractive":
                llm = MockLLM()           # 추출형: 검색 1순위 문서를 그대로(환각 0)
            else:
                from ..rag.llm import LocalLLM
                llm = LocalLLM()          # 생성형: 로컬 Qwen이 근거만으로 생성
                llm.load()                # eager 로드 — 실패를 여기 except에서 잡아 mock 폴백
            _rag_backend = backend if backend != "bge" else "bge-llm"
            logger.info("RAG 백엔드=%s (threshold=%.2f)", _rag_backend, _BGE_THRESHOLD)
            # 생성형은 표현 변주가 있어 자기일관성을 임베딩 코사인으로 판정(조사/어미만
            # 바뀐 같은 뜻 답변의 오거부 방지). 추출형은 결정론(동일 문서 반환)이라
            # lexical Jaccard 기본값으로 충분하고 추가 임베딩 호출도 아낀다.
            ct = 0.45 if backend != "bge-extractive" else 0.6
            consistency_fn = None
            if backend != "bge-extractive":
                from ..rag.embed import embed as _embed
                from ..rag.gates import semantic_consistency
                consistency_fn = (lambda samples, _e=_embed, _t=_CONSISTENCY_COS:
                                  semantic_consistency(samples, _e, _t))
            return RagPipeline(retriever, llm, score_threshold=_BGE_THRESHOLD,
                               consistency_threshold=ct, consistency_fn=consistency_fn)
        except Exception as e:  # noqa: BLE001
            logger.warning("bge RAG 로드 실패 → mock 폴백: %s", e)
    _rag_backend = "mock"
    return RagPipeline(MockRetriever(kb), MockLLM())


def _get_rag() -> RagPipeline:
    global _rag
    if _rag is None:
        with _rag_lock:               # RAG 전용 락(모델 로딩이 tables/index를 막지 않음)
            if _rag is None:
                _rag = _build_rag(_load_kb())
    return _rag


def warmup() -> None:
    """서버 기동 시 무거운 리소스를 미리 로드(첫 요청 지연 제거)."""
    _get_tables()
    _get_index()
    _get_rag()
    _get_sem_index()   # 특기 의미인덱스(494 임베딩) — bge 활성 시
    _get_bmgg()        # 사회복무 복무기관 지방청 인덱스(있으면)
    _get_sojip()       # 사회복무 소집계획 분야 집계(있으면)
    _get_jeopsu()      # 모집병 접수현황 특기별 경쟁률(있으면)
    _get_gongseok()    # 사회복무 공석 지방청 집계(있으면)
    _get_jinro()       # 병역진로설계센터 지방청 목록(있으면)


# --- 1) 백분위 진단 ----------------------------------------------------------
def list_cohorts() -> List[str]:
    cohorts = sorted({c for _, c in _get_tables()})
    # 전국을 맨 앞으로
    cohorts.sort(key=lambda c: (c != DEFAULT_COHORT, c))
    return cohorts


def _percentile_block(metric: str, value: float, cohort: str) -> dict:
    tables = _get_tables()
    table = tables.get((metric, cohort))
    label = _METRIC_LABEL.get(metric, metric)
    unit = _METRIC_UNIT.get(metric, "")
    if table is None:
        return {"metric": metric, "label": label, "value": value, "ok": False,
                "abstain_reason": "no_data",
                "message": f"{cohort} 코호트의 {label} 분포가 없어 백분위를 제공하지 않습니다."}
    r = table.percentile(value)
    return {
        "metric": metric, "label": label, "value": value, "unit": unit,
        "ok": r.ok,
        "percentile_rank": r.percentile_rank,
        "top_percent": r.top_percent,
        "abstain_reason": r.abstain_reason.value if r.abstain_reason else None,
        "covered_range": list(r.covered_range) if r.covered_range else None,
        "cohort_size": r.cohort_size,
        "message": r.as_message(label, unit=unit),
    }


def percentile_report(height_cm: float, weight_kg: float,
                      cohort: str = DEFAULT_COHORT) -> dict:
    """신장·체중 입력 → BMI 계산 후 세 지표 백분위(범위 밖은 정직하게 거부)."""
    try:
        h = float(height_cm)
        w = float(weight_kg)
    except (TypeError, ValueError):
        return {"ok": False, "error": "신장·체중은 숫자여야 합니다."}
    if not (h > 0 and w > 0):
        return {"ok": False, "error": "신장·체중은 0보다 커야 합니다."}
    if cohort not in {c for _, c in _get_tables()}:
        cohort = DEFAULT_COHORT
    bmi = round(compute_bmi(h, w), 1)
    blocks = [
        _percentile_block("bmi", bmi, cohort),
        _percentile_block("height", h, cohort),
        _percentile_block("weight", w, cohort),
    ]
    return {"ok": True, "cohort": cohort, "bmi": bmi,
            "height_cm": h, "weight_kg": w, "blocks": blocks,
            "disclaimer": "백분위는 또래 대비 위치 정보이며 신체등급/병역처분 예측이 아닙니다."}


# --- 2) 거부할 줄 아는 상담 --------------------------------------------------
def _doc_dict(d) -> dict:
    return {"source": d.source, "score": d.score,
            "snippet": d.text[:140] + ("…" if len(d.text) > 140 else "")}


def consult(query: str) -> dict:
    """RAG 상담: 답하거나(근거 출처 포함) 거부한다(사유+대체안내)."""
    q = (query or "").strip()
    if not q:
        return {"ok": False, "error": "질문을 입력하세요."}
    rag = _get_rag()
    r: RagResult = rag.answer(q)
    base = {
        "ok": True, "query": q, "answered": r.answered,
        "trust_status": r.trust_status,
        "backend": _rag_backend,
        "sources": [_doc_dict(d) for d in r.sources],
    }
    if r.answered:
        base.update({
            "answer": r.answer,
            "grounding": r.grounding,
            "consistency_ok": r.consistency_ok,
        })
    else:
        base.update({
            "refusal_reason": r.refusal_reason.value if r.refusal_reason else None,
            "refusal_message": r.refusal_message,
            "alternatives": r.alternatives,
        })
    return base


# --- 3) 모집병 특기 추천 -----------------------------------------------------
_jeopsu_rates: Optional[dict] = None


def _norm_teukgi(name: str) -> str:
    """특기명 정규화(괄호 부기·공백 제거) — 접수현황 특기명과 매칭용."""
    return re.sub(r"\(.*?\)", "", name or "").replace(" ", "").lower()


def _parse_rate(s) -> Optional[float]:
    """경쟁률 문자열 → 0 이상 실수. '*'·빈값·비수치는 None(표시 안 함)."""
    try:
        v = float(str(s).strip())
    except (TypeError, ValueError):
        return None
    return v if (math.isfinite(v) and v >= 0) else None


def _get_jeopsu() -> dict:
    """접수현황 경쟁률을 (정규화 특기명, 군) → 레코드 맵으로 로드(1회).

    - 키에 군을 포함해 공군/해군 '일반' 등 동명 이군 혼동을 막는다.
    - 괄호 부기 제거로 한 키에 서로 다른 경쟁률이 겹치면(예: 장애물운용(E)/(M),
      임기제/일반) '모호'로 보고 제외한다 — 틀린 값을 붙이느니 미표시가 정직.
    - 유효 경쟁률(수치)·선발인원>0 인 것만 채택.
    파일 없으면 {}. 읽기전용 캐시(락 생략).
    """
    global _jeopsu_rates
    if _jeopsu_rates is None:
        try:
            with open(JEOPSU_RATE, encoding="utf-8") as f:
                recs = (json.load(f) or {}).get("records", [])
        except (OSError, ValueError):
            recs = []
        m: dict = {}
        ambiguous: set = set()
        for rec in recs:
            rate = _parse_rate(rec.get("rate"))
            if rate is None or rec.get("seonbal", 0) <= 0:
                continue
            key = (_norm_teukgi(rec.get("name", "")), rec.get("gun", ""))
            if not key[0]:
                continue
            if key in m and m[key]["rate"] != rate:
                ambiguous.add(key)          # 같은 (정규화명,군)에 다른 경쟁률 → 모호
            else:
                m[key] = {"rate": rate, "jeopsu": rec.get("jeopsu", 0),
                          "seonbal": rec.get("seonbal", 0), "yy": rec.get("yy", 0)}
        for key in ambiguous:
            m.pop(key, None)                # 모호 키 전부 제외
        _jeopsu_rates = m
    return _jeopsu_rates


def teukgi_competition(teukgi_name: str, branch: str = "") -> Optional[dict]:
    """특기(특기명+군)의 모집 스냅샷 경쟁률(접수현황 15031295).

    매칭이 없거나 모호하면 None — 지어내거나 다른 모집단위 값을 붙이지 않는다.
    경쟁률은 참고 스냅샷이며 개인 합격·선발 예측이 아니다(정직성).
    """
    rec = _get_jeopsu().get((_norm_teukgi(teukgi_name), (branch or "").strip()))
    if not rec:
        return None
    return {
        "rate": rec["rate"], "jeopsu": rec["jeopsu"], "seonbal": rec["seonbal"],
        "yy": rec["yy"],
        "caveat": "모집 스냅샷 경쟁률(참고용, 합격/선발 예측 아님).",
    }


def _match_dict(m) -> dict:
    return {
        "teukgi_name": m.rule.teukgi_name,
        "branch": m.rule.branch,
        "qualification": m.rule.qualification,
        "grade_req": m.rule.grade_req,
        "status": m.status,
        "qualifies": m.qualifies,
        "verification_required": m.verification_required,
        "matched_on": m.matched_on,
        "relevance": m.relevance,
        "reason": m.reason,
        "competition": teukgi_competition(m.rule.teukgi_name, m.rule.branch),
    }


def _get_sem_index():
    """특기 의미인덱스(bge-m3 494 임베딩) lazy 빌드. 실패/비활성 시 None."""
    global _sem_index
    if not _USE_SEM_TEUKGI:
        return None
    if _sem_index is None:
        with _sem_lock:
            if _sem_index is None:
                try:
                    from ..recommend.semantic import TeukgiSemanticIndex
                    _sem_index = TeukgiSemanticIndex(_get_index())
                    logger.info("특기 의미인덱스(bge-m3) 빌드 완료 (%d특기)", len(_sem_index.keys))
                except Exception as e:  # noqa: BLE001 — 실패 시 lexical 폴백
                    logger.warning("특기 의미인덱스 빌드 실패 → lexical 폴백: %s", e)
                    _sem_index = False
    return _sem_index or None


def recommend_teukgi(majors: Optional[List[str]] = None,
                     certificates: Optional[List[str]] = None,
                     interests: Optional[List[str]] = None,
                     preferred_branches: Optional[List[str]] = None,
                     top_k: int = 5) -> dict:
    """전공·자격·관심 → 특기 추천(자격충족=검증, 관련도=랭킹 분리)."""
    index = _get_index()
    if not index:
        return {"ok": False, "error": "특기 인덱스가 없습니다(teukgi_index.json 미생성)."}
    profile = UserProfile(
        majors=[s for s in (majors or []) if s and s.strip()],
        certificates=[s for s in (certificates or []) if s and s.strip()],
        interests=[s for s in (interests or []) if s and s.strip()],
        preferred_branches=[s for s in (preferred_branches or []) if s and s.strip()],
    )
    if not profile.all_holdings() and not profile.interests:
        return {"ok": False, "error": "전공·자격·관심사 중 하나 이상 입력하세요."}
    try:
        k = max(1, min(int(top_k), 20))
    except (TypeError, ValueError):
        k = 5

    # bge-m3 의미매칭(가용 시): 프로필 텍스트로 494특기 코사인 관련도 → 정확한 의미 랭킹
    sem_scores, rel_kind, min_rel = None, "lexical", 0.05
    sem = _get_sem_index()
    if sem is not None:
        profile_text = " ".join([*profile.majors, *profile.interests, *profile.certificates])
        sem_scores = sem.scores(profile_text)
        rel_kind, min_rel = "bge-m3", _SEM_MIN_REL   # 임시 컷오프(평가 전 휴리스틱)
    matches = recommend_from_index(profile, index, top_k=k,
                                   min_relevance=min_rel, sem_scores=sem_scores)
    return {"ok": True, "n_total_teukgi": len(index), "relevance": rel_kind,
            "matches": [_match_dict(m) for m in matches],
            "disclaimer": "자격충족은 공개 요건 대비 검증값이며 선발/합격을 보장하지 않습니다."}


# --- 5) 병역 준비 경로 생성 (F4 복원 — 백분위·특기를 '다음 행동'으로 엮는 접착제) ---
# 규칙 기반 결정론 오케스트레이션(LLM/학습 없음). 이미 계산된 percentile/teukgi
# 결과 dict를 받아 5단계 로드맵 문장에 '내 결과'를 인용한다.
# 실 URL은 죽은 버튼 방지 위해 안정적인 공식 도메인만 사용한다(회차별 딥링크 지양).
MMA_LINKS = {
    "exam": {"label": "병무청 병역판정검사 안내", "url": "https://www.mma.go.kr/"},
    "portal": {"label": "병무청 모집병 지원", "url": "https://www.mma.go.kr/"},
    "social": {"label": "사회복무 포털(복무기관 조회)", "url": "https://sbg.mma.go.kr/"},
    "career": {"label": "병역진로설계센터 안내", "url": "https://www.mma.go.kr/"},
}


_bmgg_regions: Optional[dict] = None


def _get_bmgg() -> dict:
    """사회복무 복무기관 지방청별 인덱스 로드(1회, 파일 없으면 {}).

    읽기전용 캐시라 첫 동시호출이 파일을 두 번 읽어도 무해 → 락 생략(ponytail).
    """
    global _bmgg_regions
    if _bmgg_regions is None:
        try:
            with open(BMGG_INDEX, encoding="utf-8") as f:
                _bmgg_regions = (json.load(f) or {}).get("regions", {})
        except (OSError, ValueError):
            _bmgg_regions = {}          # 미수집(활용신청 전/스크립트 미실행) → 정적 안내로 폴백
    return _bmgg_regions


_sojip_plan: Optional[dict] = None


def _get_sojip() -> Optional[dict]:
    """사회복무 소집계획 분야별 집계 로드(1회, 없으면 None). 읽기전용 캐시(락 생략)."""
    global _sojip_plan
    if _sojip_plan is None:
        try:
            with open(SOJIP_PLAN, encoding="utf-8") as f:
                _sojip_plan = json.load(f) or {}
        except (OSError, ValueError):
            _sojip_plan = {}
    return _sojip_plan or None


def convocation_plan(top: int = 5) -> Optional[dict]:
    """사회복무 소집계획(3066753) 분야별 계획인원 집계 — 담당자/로드맵 참고 인사이트."""
    plan = _get_sojip()
    if not plan or not plan.get("fields"):
        return None
    meta = plan.get("_meta", {})
    return {
        "year": meta.get("year", ""),
        "total_pcnt": meta.get("total_pcnt", 0),
        "field_count": meta.get("field_count", len(plan["fields"])),
        "top_fields": plan["fields"][:max(0, top)],
        "source": meta.get("source", "병무청 사회복무 연도별 소집계획 API(3066753)"),
    }


_gongseok_regions: Optional[dict] = None


def _get_gongseok() -> dict:
    """사회복무 공석 지방청별 집계 로드(1회, 없으면 {}). 읽기전용 캐시(락 생략)."""
    global _gongseok_regions
    if _gongseok_regions is None:
        try:
            with open(GONGSEOK_INDEX, encoding="utf-8") as f:
                _gongseok_regions = (json.load(f) or {}).get("regions", {})
        except (OSError, ValueError):
            _gongseok_regions = {}
    return _gongseok_regions


def social_vacancies(region_label: str) -> Optional[dict]:
    """지방청의 사회복무 본인선택 공석 집계(3066754). 없으면 None(폴백).

    실시간 스냅샷의 현재 배정 규모·표본을 안내한다. 개인 배정/처분 예측이 아니며,
    재수집 시 값이 변한다(정직성).
    """
    region = (region_label or "").strip()
    r = _get_gongseok().get(region)
    if not r:
        return None
    return {
        "region": region, "baejeong": r.get("baejeong", 0),
        "records": r.get("records", 0), "sample": r.get("sample", [])[:4],
        "source": "병무청 사회복무 본인선택 공석 API(3066754)",
        "caveat": "실시간 스냅샷(재수집 시 변동, 개인 배정/처분 예측 아님).",
    }


_jinro_centers: Optional[dict] = None
_jinro_meta: dict = {}


def _get_jinro() -> dict:
    """진로설계센터 지방청별 목록 로드(1회, 없으면 {}). 읽기전용 캐시(락 생략)."""
    global _jinro_centers, _jinro_meta
    if _jinro_centers is None:
        try:
            with open(JINRO_CENTERS, encoding="utf-8") as f:
                payload = json.load(f) or {}
        except (OSError, ValueError):
            payload = {}
        _jinro_centers = payload.get("regions", {})
        _jinro_meta = payload.get("_meta", {})
    return _jinro_centers


def career_centers(region_label: str) -> Optional[dict]:
    """지방청 관할 병역진로설계센터(15148370). 없으면 None(→ 공식 링크 폴백).

    주소·전화는 변동 가능한 사실 데이터라 as_of(자료 기준일)를 함께 노출한다(정직).
    """
    centers = _get_jinro().get((region_label or "").strip())
    if not centers:
        return None
    return {"region": region_label, "centers": centers,
            "as_of": _jinro_meta.get("data_date", ""),
            "source": "병무청 병역진로설계지원센터 위치(15148370)"}


def social_agencies(region_label: str, limit: int = 4) -> Optional[dict]:
    """지방청(신검 코호트에서 '2026_' 제거값)의 실제 사회복무 복무기관 조회.

    신검 코호트명 == 사회복무 gtcdNm(전국 제외)이라 그대로 매칭한다. 데이터/매칭이
    없으면 None → 로드맵은 기존 정적 안내로 폴백. 개인 배정 예측이 아니라 '기관 속성
    표시'다(선발제한 여부는 기관 특성일 뿐 개인 처분과 무관).
    """
    region = (region_label or "").strip()
    rows = _get_bmgg().get(region)
    if not rows:
        return None
    return {
        "region": region,
        "total": len(rows),
        "items": rows[:max(0, limit)],
        "source": "병무청 사회복무요원 복무기관 API(3066757)",
        "caveat": "기관 속성 표시일 뿐 개인 복무기관 배정/처분 예측이 아닙니다.",
    }


def _matches_by_status(teukgi: dict, statuses: tuple) -> list:
    """teukgi 결과에서 주어진 status의 match만 추출(키/None 방어)."""
    if not teukgi.get("ok"):
        return []
    return [m for m in (teukgi.get("matches") or [])
            if m.get("status") in statuses]


def build_roadmap(profile: dict, percentile: dict, teukgi: dict) -> dict:
    """percentile/teukgi 결과를 5단계 개인 로드맵으로 직조한다.

    각 단계: n/title/text(내 결과 인용)/tone(ok|warn|info)/link/ask(후속 상담 프리필).
    """
    steps = []
    cohort_label = (percentile.get("cohort") or "").replace("2026_", "") or "전국"

    # 1단계 — 검사 일정·통지 확인
    steps.append({
        "n": 1, "title": "병역판정검사 일정·통지 확인", "tone": "info",
        "text": "병역판정검사 통지서의 검사 일자·장소를 확인하세요(보통 만 19세). "
                "일정 변경·연기는 병무청 누리집에서 신청합니다.",
        "link": MMA_LINKS["exam"], "ask": "병역판정검사는 어디서 받나요?",
    })

    # 2단계 — 신검 준비 (백분위 인용)
    blocks = percentile.get("blocks", []) if percentile.get("ok") else []
    abstained = [b for b in blocks if not b.get("ok")]
    bmi = next((b for b in blocks if b.get("metric") == "bmi"), None)
    if not percentile.get("ok"):
        s2_text, s2_tone = ("신장·체중을 입력하면 또래 대비 위치를 확인할 수 있어요.", "info")
    elif abstained:
        names = ", ".join(b.get("label") or b.get("metric") or "항목" for b in abstained)
        s2_text, s2_tone = (
            f"입력값 중 {names}이(가) 공개데이터 표시 범위 밖이라 '판단 보류'입니다. "
            f"수치를 지어내지 않으며, 검사 전 보건소·상담으로 확인하세요. "
            f"(또래 위치 정보일 뿐 신체등급 예측이 아닙니다.)", "warn")
    elif bmi and bmi.get("ok"):
        s2_text, s2_tone = (
            f"BMI는 또래({cohort_label}) 기준 백분위 {bmi.get('percentile_rank', '확인 불가')}로 "
            f"공개데이터 범위 내입니다. 표준 신검 준비물을 챙기세요. "
            f"(또래 위치 정보일 뿐 신체등급 예측이 아닙니다.)", "ok")
    else:
        s2_text, s2_tone = ("백분위 결과를 확인하세요. (신체등급 예측이 아닙니다.)", "ok")
    steps.append({"n": 2, "title": "신체검사 준비", "tone": s2_tone, "text": s2_text,
                  "link": MMA_LINKS["exam"], "ask": "병역판정검사 준비물은 무엇인가요?"})

    # 3단계 — 관심 특기 확인 (특기 인용). 검증충족(ok)만 '1순위', unknown은 본인확인으로 분리.
    quals = _matches_by_status(teukgi, ("ok",))
    unknowns = _matches_by_status(teukgi, ("unknown",))
    if not teukgi.get("ok"):
        s3_text, s3_tone = ("전공·자격·관심사를 입력하면 지원 자격을 검토할 수 있는 "
                            "모집병 특기를 추천받을 수 있어요.", "info")
    elif quals:
        top = quals[0]
        s3_text, s3_tone = (
            f"보유 자격으로 지원 자격을 검토할 수 있는 1순위는 "
            f"'{top.get('teukgi_name', '이름 미상 특기')}'({top.get('branch', '군 미상')}) 입니다. "
            f"(합격 보장이 아니라 지원 자격 검토 가능 수준입니다.)", "ok")
    elif unknowns:
        top = unknowns[0]
        s3_text, s3_tone = (
            f"관련도 높은 후보로 '{top.get('teukgi_name', '이름 미상 특기')}'"
            f"({top.get('branch', '군 미상')})가 있으나, 자격 등급·요건은 본인 확인이 "
            f"필요합니다.", "warn")
    else:
        s3_text, s3_tone = ("전공·관심 관련 특기는 있으나 현재 보유 자격으로 충족되는 특기는 "
                            "확인되지 않았습니다. 자격 요건을 확인해 보세요.", "info")
    steps.append({"n": 3, "title": "모집병 특기 확인", "tone": s3_tone, "text": s3_text,
                  "link": MMA_LINKS["portal"], "ask": "모집병은 어떻게 지원하나요?"})

    # 4단계 — 자격 보완 + 현역/보충역 둘 다 준비(정직성=구조)
    nv = _matches_by_status(teukgi, ("unknown", "grade"))
    if nv:
        names = ", ".join(m.get("teukgi_name", "이름 미상 특기") for m in nv[:3])
        s4_lead = f"다음 특기는 등급·점수 요건의 본인 확인/보완이 필요합니다: {names}. "
    else:
        s4_lead = ""
    step4 = {
        "n": 4, "title": "현역·보충역 두 경로 모두 준비", "tone": "info",
        "text": s4_lead +
                "현역·보충역 중 어느 쪽일지는 병역판정검사로 결정됩니다. 본 서비스는 결과를 "
                "단정하지 않고 두 경로를 모두 준비하도록 안내합니다. 보충역(사회복무) 대비는 "
                "복무기관·소집 일정을 미리 조회해 두세요.",
        "link": MMA_LINKS["social"], "ask": "사회복무요원 복무기관 조회",
    }
    # 내 지방청 실제 복무기관(병무청 3066757 실데이터)을 붙여 정적 링크를 근거로 승격.
    agencies = social_agencies(cohort_label, limit=4)
    if agencies:
        eg = ", ".join(a.get("nm", "") for a in agencies["items"][:2] if a.get("nm"))
        step4["text"] += (f" {cohort_label} 관할 복무기관은 병무청 공개데이터 기준 "
                          f"{agencies['total']}곳입니다(예: {eg} 등, 아래 표 참고).")
        step4["agencies"] = agencies
    plan = convocation_plan(top=3)
    if plan and plan.get("top_fields"):
        top = plan["top_fields"][0]
        step4["text"] += (f" {plan['year']}년 사회복무 소집계획은 전국 계획인원 "
                          f"{plan['total_pcnt']:,}명(최다 분야: {top['name']} {top['pcnt']:,}명)입니다.")
        step4["convocation"] = plan
    vac = social_vacancies(cohort_label)
    if vac:
        step4["text"] += (f" {cohort_label} 관할 본인선택 공석은 병무청 스냅샷 기준 "
                          f"{vac['records']:,}건(배정 {vac['baejeong']:,}명)입니다"
                          f"(공개 공석 배정인원 합계이며 개인 배정 가능성 예측이 아닙니다).")
        step4["vacancies"] = vac
    steps.append(step4)

    # 5단계 — 진로설계센터 상담 예약 (실 CTA)
    step5 = {
        "n": 5, "title": "병역진로설계센터 상담", "tone": "info",
        "text": "맞춤 상담과 최종 안내는 병역진로설계센터를 이용하세요. "
                "본 카드는 다음 행동을 돕는 참고 정보이며, 최종 병역처분은 병역판정검사로 결정됩니다.",
        "link": MMA_LINKS["career"], "ask": "병무청 진로 상담 예약",
    }
    centers = career_centers(cohort_label)
    if centers:
        eg = centers["centers"][0]
        asof = f" ({centers['as_of']} 기준)" if centers.get("as_of") else ""
        step5["text"] += (f" {cohort_label} 관할은 '{eg.get('name', '')}'"
                          f"({eg.get('addr', '')}, {eg.get('tel', '')})입니다{asof}.")
        step5["centers"] = centers
    steps.append(step5)

    return {"ok": True, "steps": steps,
            "note": "로드맵은 다음 행동 안내일 뿐, 최종 병역처분은 병역판정검사로 결정됩니다."}


def roadmap_report(height_cm, weight_kg, cohort: str = DEFAULT_COHORT,
                   majors=None, certificates=None, interests=None,
                   preferred_branches=None) -> dict:
    """단일 입력 → 백분위 + 특기 + 로드맵을 한 번에(프런트 왕복 1회)."""
    pr = percentile_report(height_cm, weight_kg, cohort)
    if not pr.get("ok"):
        return {"ok": False, "stage": "percentile",
                "error": pr.get("error", "신장·체중을 확인하세요.")}
    has_profile = any(x for x in (majors, certificates, interests) if x)
    if has_profile:
        tr = recommend_teukgi(majors=majors, certificates=certificates,
                              interests=interests, preferred_branches=preferred_branches)
    else:
        tr = {"ok": False, "skipped": True,
              "error": "전공·자격·관심사 미입력 — 특기 추천 생략"}
    profile = {"height_cm": pr["height_cm"], "weight_kg": pr["weight_kg"],
               "cohort": pr["cohort"], "bmi": pr["bmi"]}
    roadmap = build_roadmap(profile, pr, tr)
    return {"ok": True, "profile": profile, "percentile": pr,
            "teukgi": tr, "roadmap": roadmap}


def classify_query(text: str) -> dict:
    """민원 질문 5범주 분류(F5) — 상담 입력 카테고리 태깅용."""
    q = (text or "").strip()
    if not q:
        return {"ok": False, "error": "질문을 입력하세요."}
    category, scores = _classify(q)
    return {"ok": True, "category": category, "scores": scores}


def _load_eval_texts(*names) -> list:
    out = []
    for name in names:
        p = os.path.join(EVAL, name)
        if os.path.exists(p):
            out += [it["text"] for it in json.load(open(p, encoding="utf-8")) if it.get("text")]
    return out


def complaint_stats() -> dict:
    """민원 유형 자동 분류 집계 + intent_gate 자동거부/응답 추정 (B2G 행정 인사이트).

    실 민원 로그가 없으므로 독립 골드셋(분류·거부)을 데모 코퍼스로 사용한다.
    병무청은 (1) 어떤 유형 질문이 많은지 (2) 얼마나 자동응답/거부 가능한지를 본다.
    """
    from ..rag.gates import intent_gate
    corpus = _load_eval_texts("classify_set.json", "classify_test.json",
                              "refusal_set.json", "refusal_test.json")
    if not corpus:
        return {"ok": False, "error": "골드셋이 없어 집계할 수 없습니다."}
    cats, auto_refuse = {}, 0
    for q in corpus:
        cat = _classify(q)[0]
        cats[cat] = cats.get(cat, 0) + 1
        if intent_gate(q):
            auto_refuse += 1
    total = len(corpus)
    dist = sorted(({"category": c, "count": n, "pct": round(100 * n / total, 1)}
                   for c, n in cats.items()), key=lambda x: x["count"], reverse=True)
    return {
        "ok": True, "total": total, "distribution": dist,
        "auto_refuse": auto_refuse, "answerable": total - auto_refuse,
        "auto_refuse_pct": round(100 * auto_refuse / total, 1),
        "note": f"데모셋 {total}건(분류·거부 독립 골드셋) 기준 추정 — 실 민원 로그 아님. "
                "자동거부=개인판정/의료/예측 등 위험질문을 intent 게이트가 차단한 비율.",
    }


# --- 4) AI 신뢰도(AI30 메트릭) ----------------------------------------------
def metrics() -> dict:
    """eval/report.json(독립 골드셋 측정 결과)을 그대로 노출."""
    if not os.path.exists(REPORT):
        return {"ok": False, "error": "report.json 없음 — scripts/run_eval.py 먼저 실행."}
    try:
        with open(REPORT, encoding="utf-8") as f:
            report = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        return {"ok": False, "error": f"report.json 읽기 실패: {e}"}
    if not isinstance(report, dict):
        return {"ok": False, "error": "report.json 형식 오류(dict 아님)."}
    return {"ok": True, "report": report}


# --- 6) B2G 14지방청 청년건강 히트맵 (F7 — 준-전수 신검 데이터 기반) ----------
DATA_YEAR = "2026"

# 외부 참고 벤치마크(질병관리청 국민건강영양조사). 표본조사·측정기준이 신검과 달라
# 직접 비교는 '참고'로만 — 수치는 근사이며 출처/주의를 함께 노출(정직성).
KNHANES_REF = {
    "label": "국민건강영양조사(KNHANES) 19–29세 남성, BMI≥25 비율",
    "metric": "bmi",
    "threshold": 25,            # 비교 기준을 명시(국내 비만 기준=BMI≥25)
    "rate_approx": 40.0,        # BMI≥25 약 40%(연도별 변동)
    "compare_to": "over25",     # 병무청 전국 'BMI≥25 비율'과 같은 기준으로 비교
    "source": "질병관리청 국민건강영양조사",
    "caveat": "표본조사(자가·측정)이며 병무청 신검(준-전수, BMI 18.5~35 절단)과 측정·표본 기준이 달라 직접 비교는 참고용.",
}



def _dist_stats(table: DistributionTable) -> Optional[dict]:
    """히스토그램에서 n/평균/중앙값 산출(bin 중점·균등 가정)."""
    total = table.total
    if total <= 0:
        return None
    mean = sum(((b.low + b.high) / 2) * b.count for b in table.bins) / total
    target, cum, median = total / 2, 0, table.bins[-1].high
    for b in table.bins:
        if cum + b.count >= target:
            frac = (target - cum) / b.count if b.count else 0.0
            median = b.low + frac * (b.high - b.low)
            break
        cum += b.count
    return {"n": total, "mean": round(mean, 1), "median": round(median, 1),
            "min": table.vmin, "max": table.vmax}


def _share_ge(table: DistributionTable, threshold: float) -> Optional[float]:
    """값 ≥ threshold 비율(%) — percentile 역산(범위 내일 때만)."""
    r = table.percentile(threshold)
    if not r.ok:
        return None
    return round(100.0 - r.percentile_rank, 1)


def b2g_heatmap(metric: str = "bmi") -> dict:
    """14지방청별 신검 통계 히트맵(중앙값 + BMI 과체중/비만 비율). 전국은 기준선."""
    metric = metric if metric in ("bmi", "height", "weight") else "bmi"
    tables = _get_tables()
    rows = []
    for cohort in {c for _, c in tables}:
        if cohort == DEFAULT_COHORT:
            continue
        table = tables.get((metric, cohort))
        st = _dist_stats(table) if table else None
        if not st:
            continue
        row = {"cohort": cohort.replace("2026_", ""), **st}
        if metric == "bmi":
            row["over25"] = _share_ge(table, 25.0)   # 과체중+ 비율(절단 범위 내)
            row["over30"] = _share_ge(table, 30.0)   # 비만 비율
        rows.append(row)
    rows.sort(key=lambda r: r["median"], reverse=True)
    nat_table = tables.get((metric, DEFAULT_COHORT))
    national = _dist_stats(nat_table) if nat_table else None
    reference = None
    if metric == "bmi" and nat_table:
        # 병무청 준-전수 전국 과체중+ 비율 + 질병청 표본 참고치를 나란히(표본 vs 준-전수)
        national = {**national, "over25": _share_ge(nat_table, 25.0),
                    "over30": _share_ge(nat_table, 30.0)}
        reference = KNHANES_REF
    return {
        "ok": True, "metric": metric, "label": _METRIC_LABEL[metric],
        "unit": _METRIC_UNIT[metric], "data_year": DATA_YEAR,
        "national": national, "rows": rows, "reference": reference,
        "note": "병무청 병역판정검사(3064321) 준-전수 데이터 기반 지방청별 청년건강 통계. "
                f"{DATA_YEAR} 단년(연차 축적 시 추세 분석 가능). "
                "BMI는 공개데이터 18.5~35 절단이라 비율은 범위 내 기준.",
    }


def status() -> dict:
    """데모 상태(데이터 출처/규모) — UI 헤더 배지용."""
    tables = _get_tables()
    total = next(iter(tables.values())).total if tables else 0
    index = _get_index()
    return {
        "ok": True,
        "distribution_source": _dist_source,
        "cohort_count": len({c for _, c in tables}),
        "cohort_size": total,
        "teukgi_count": len(index),
        "kb_source": "demo",
        "rag_backend": _rag_backend or f"(미로드, 설정={RAG_BACKEND})",
    }
