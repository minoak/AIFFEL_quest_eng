# samples/ — 바로 돌려볼 수 있는 샘플 3장

Test 30장 holdout 에서 **등급이 다른 3장**을 골라 이미지·GT 마스크·기대 출력을 함께 두었다.
`src/RISK_ASSESSOR_V5.ipynb` 에 이 이미지를 넣고 결과를 `expected_outputs.json` 과 비교하면 된다.

| 파일 | 기대 등급 | 활성 경고 |
|---|---|---|
| `night ride (98).png` | **안전** | 없음 (moveable 4개 있으나 전부 안전 거리) |
| `Screenshot (417).png` | **주의** | BSW — 우측 4.9m 측면 접근 |
| `Screenshot (322).png` | **위험** | LDW — 좌측 이탈 (49%) |

## 구성

- `images/` — 입력 프레임 (1920×1080, 데이터셋 원본)
- `masks/` — 데이터셋 제공 GT 세그멘테이션 라벨 (uint8 PNG, 픽셀값 = 클래스 0~6).
  세그 모델 없이 mask 주입 경로로 파이프라인만 확인할 때 입력으로 쓸 수 있다.
- `expected_outputs.json` — 원 평가 (`v5_testset_results.json`, Test 30장) 에서
  해당 3장을 그대로 추출한 기대 출력. 재계산하지 않았다.

## 주의

기대 출력은 **U-Net 5-fold ensemble + Depth Pro** 조합으로 나온 값이다.
단일 fold 체크포인트나 depth 없이 돌리면 거리·mIoU 수치가 달라질 수 있다
(등급 판정은 대체로 유지되지만 보장하지 않음).
