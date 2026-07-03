"""FastAPI 서버 — 통합 데모. 라우트는 service.py 순수 함수만 호출한다.

실행:  python scripts/run_server.py   (또는)  uvicorn mma_navi.app.server:app
"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import service

logger = logging.getLogger("mma_navi")
WEB_DIR = os.path.join(service.ROOT, "web")


def _warmup_bg() -> None:
    try:
        service.warmup()
        logger.info("warmup 완료 (RAG=%s)", service._rag_backend)
    except Exception:  # noqa: BLE001
        logger.exception("warmup 실패 — 일부 기능이 제한될 수 있습니다")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 무거운 리소스(분포/인덱스/RAG 모델)를 백그라운드 스레드에서 미리 로드.
    # bge-m3/LLM 로딩이 서버 기동을 막지 않게 하고, 데이터 미비여도 서버는 뜬다.
    import threading
    threading.Thread(target=_warmup_bg, daemon=True).start()
    yield


app = FastAPI(title="병역준비 AI 내비게이터", version="0.1",
              description="근거가 없으면 답하지 않는 병역 준비 AI (통합 데모)",
              lifespan=lifespan)


# --- 요청 모델 ---------------------------------------------------------------
class PercentileReq(BaseModel):
    height_cm: float = Field(..., description="신장(cm)")
    weight_kg: float = Field(..., description="체중(kg)")
    cohort: str = service.DEFAULT_COHORT


class ConsultReq(BaseModel):
    query: str


class ClassifyReq(BaseModel):
    query: str


class RoadmapReq(BaseModel):
    height_cm: float = Field(..., description="신장(cm)")
    weight_kg: float = Field(..., description="체중(kg)")
    cohort: str = service.DEFAULT_COHORT
    majors: List[str] = []
    certificates: List[str] = []
    interests: List[str] = []
    preferred_branches: List[str] = []


class TeukgiReq(BaseModel):
    majors: List[str] = []
    certificates: List[str] = []
    interests: List[str] = []
    preferred_branches: List[str] = []
    top_k: int = 5


# --- API 라우트 --------------------------------------------------------------
@app.get("/api/status")
def api_status():
    return service.status()


@app.get("/api/cohorts")
def api_cohorts():
    return {"ok": True, "cohorts": service.list_cohorts()}


@app.post("/api/percentile")
def api_percentile(req: PercentileReq):
    return service.percentile_report(req.height_cm, req.weight_kg, req.cohort)


@app.post("/api/consult")
def api_consult(req: ConsultReq):
    return service.consult(req.query)


@app.post("/api/classify")
def api_classify(req: ClassifyReq):
    return service.classify_query(req.query)


@app.post("/api/roadmap")
def api_roadmap(req: RoadmapReq):
    return service.roadmap_report(
        req.height_cm, req.weight_kg, req.cohort,
        majors=req.majors, certificates=req.certificates,
        interests=req.interests, preferred_branches=req.preferred_branches)


@app.post("/api/teukgi")
def api_teukgi(req: TeukgiReq):
    return service.recommend_teukgi(
        majors=req.majors, certificates=req.certificates,
        interests=req.interests, preferred_branches=req.preferred_branches,
        top_k=req.top_k)


@app.get("/api/metrics")
def api_metrics():
    return service.metrics()


@app.get("/api/b2g")
def api_b2g(metric: str = "bmi"):
    return service.b2g_heatmap(metric)


@app.get("/api/complaints-stats")
def api_complaints_stats():
    return service.complaint_stats()


# --- 정적 파일 / 프런트 -------------------------------------------------------
@app.get("/")
def index():
    idx = os.path.join(WEB_DIR, "index.html")
    if os.path.exists(idx):
        return FileResponse(idx)
    return JSONResponse({"ok": False, "error": "web/index.html 없음"}, status_code=404)


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
