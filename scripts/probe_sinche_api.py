"""신체검사 API(3064321) 스키마 프로브.

키가 활성화되면 이 스크립트가 실제 XML 응답과 필드명을 보여준다.
그걸로 파서 매핑을 확정하고 분포를 만든다.

실행(네트워크 필요, sandbox off):
    python scripts/probe_sinche_api.py
"""
import os
import sys

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "src"))


def _load_env():
    if os.environ.get("MMA_SERVICE_KEY"):
        return
    env_path = os.path.join(ROOT, ".env")
    if os.path.exists(env_path):
        for line in open(env_path, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())


def main():
    _load_env()
    from mma_navi.mma_api import call_raw, parse_items, SINCHE_GETLIST, ApiError, compute_bmi

    print("=== 원시 응답 (numOfRows=3) ===")
    try:
        raw = call_raw(SINCHE_GETLIST, pageNo=1, numOfRows=3)
    except ApiError as e:
        print(f"[실패] {e}")
        print("\n→ 'Unauthorized'면 키 활성화 지연(승인 후 ~1시간). 잠시 뒤 재시도하세요.")
        return 1
    print(raw[:2000])

    print("\n=== 파싱된 첫 레코드 ===")
    try:
        items = parse_items(raw)
    except ApiError as e:
        print(f"[파싱 실패] {e}")
        return 1
    if not items:
        print("item 없음 — 응답 구조 확인 필요(위 원시 응답 참고)")
        return 1
    rec = items[0]
    for k, v in rec.items():
        print(f"  {k} = {v}")

    # 신장·체중이 있으면 BMI 계산 가능성 확인
    print("\n=== 필드 추정 ===")
    print("필드명 목록:", list(rec.keys()))
    print("→ 위 태그명으로 파서 매핑을 확정하고, 신장+체중이 개인단위면 BMI 직접 계산 가능")
    return 0


if __name__ == "__main__":
    sys.exit(main())
