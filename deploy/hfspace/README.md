---
title: 병역길잡이
emoji: 🧭
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: other
---

# 병역길잡이

근거가 없으면 답하지 않는 병역 준비 도우미 · 2026 공공데이터·AI 경진대회 출품작.

입력 한 번 → "나의 병역 준비 카드": 또래 백분위 · 지원 가능 특기(bge-m3 의미랭킹) ·
준비 로드맵 · 근거 기반 상담(위험질문 자동 거부). GPU·인증키 없이 CPU로 동작.

소스: https://github.com/freak-jaeuk/mma-navi

> 첫 요청 시 bge-m3 임베딩 모델을 로드하므로 수십 초 걸릴 수 있습니다(이후 캐시).
> 개인 병역처분을 예측하지 않으며, 근거가 부족하면 답변을 거부합니다.
