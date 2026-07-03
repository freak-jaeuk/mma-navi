# 픽스처 데이터 (합성 — SAMPLE)

`distributions_sample.csv`는 **엔진 검증용 합성 데이터**다. 실제 병무청 API 데이터가 아니다.

- 스키마는 실제와 동일: `metric, cohort, bin_low, bin_high, count`
- BMI는 공개 API와 동일하게 **18.5~35로 절단**(저체중/고도비만 꼬리 없음)
- 신장은 **지방청 코호트**(전국/서울 샘플) 구조

실제 데이터 교체:
- BMI/신장/체중: data.go.kr **3064321** (신검 정보, 실시간 API)
- 신장 14지방청: data.go.kr **15117367** (연간 CSV)

키 확보 후 `dataio.fetch_distribution_api`에 파서를 구현하고 동일 스키마 CSV로 캐시하면
엔진은 그대로 동작한다.
