# 야간 오토바이 블랙박스 위험도 평가 시스템

> **"한문철 TV + 스카우터"**  야간 오토바이 주행 영상에서 프레임 단위 위험도(안전/주의/위험/치명)를 자동 판정하는 후처리 파이프라인

**AIFFEL DLthon** · 2026.04.22 ~ 04.24 (3일) · **후처리 파이프라인 설계·구현**


[최종 HUD  4 bin 대표 프레임 (안전/주의/위험/치명)]
<img width="836" height="566" alt="hud_samples" src="https://github.com/user-attachments/assets/c7177a14-2174-42d8-ac60-20fea0cdafae" />



## 결과

| 지표 | 값 |
|---|---|
| Domain 판정 (GT 보유 9장) | **Exact 9/9 (100%)** |
| Segmentation mIoU(fg) | 0.7845 ± 0.0100 (5-fold) |
| Lane Mark IoU | 0.3611 (5-fold ensemble, +2.2%p) |
| 시스템 버전 | v2.6 → **v6** (7회 전면 개편) |


## 시스템 구조 (v5 final)

```
Seg Ensemble (5-fold majority vote)
  → Ego Anchor        내 오토바이 마스크 분리 (중앙 하단 prior)
  → VP + Lane + Depth 기본 feature 추출
  → Distance Fusion   3-estimator (ground / size / depth)
  → Zone Corridor     parametric 4-zone 사다리꼴 (critical/danger/caution/sidelobe)
  → 4 독립 경고        FCW · LDW · BSW · HEAD
  → bin = max(severities)   ← 가중치 합산 없음
```

## 핵심 설계 결정  가설 주도 개발

시스템의 각 축은 데이터로 검증한 가설 위에 서 있다. 전체 6개 중 핵심 3개:

**H4  "점수 합산 자체가 잘못된 추상화다"** (터닝포인트)
벌점 가산 방식(v2.6~v4)은 파라미터 튜닝 지옥으로 이어졌다 (Exact 5/10 → 2/10 하락). 위험 신호를 하나의 점수로 합치는 대신 **4개 독립 경고의 max**를 취하는 구조로 전환하자 즉시 6/10으로 반등, 이후 모든 개선이 이 위에서 이루어졌다. 복잡도 추가가 아니라 추상화 교체가 돌파구였다.

**H5  "거리 값보다 zone + confidence"**
Mobileye/OpenPilot 등 업계 관행 리서치가 같은 방향으로 수렴: bbox foot-point 기준, lane-width 정규화, 해상도 독립적인 parametric zone. 원근 사다리꼴 4-zone corridor로 구현.

**H6  "모르는 건 모른다고 말한다"**
측정 불가 상황(lateral > 70%)을 억지로 판정하지 않고 guard 처리. 
최종 Exact 9/9는 이 guard까지 적용한 v5에서 달성. 
이 원칙을 전면 확장한 실험이 v6("신뢰 구간만 말하기")이며, 답한 케이스의 정확도 대신 커버리지를 희생한다(Exact 5/9).

## 기록된 실패

- **Apple Depth Pro 전면 교체 시도**: 기술적으로 성공 (metric depth + focal 자동 추정 동작 확인). 그러나 GT 라벨 체계가 거리 기반이 아닌 시나리오 기반이라 판정 정확도가 9→6으로 하락 → **롤백**. 더 정확한 측정이 더 좋은 판정을 보장하지 않는다.
- **v3.x hierarchical + 파라미터 튜닝**: local optimum의 전형. 구조를 바꾸지 않는 튜닝은 2/10까지 악화시켰다.

## 파일 안내

| 파일 | 내용 |
|---|---|
| [위험도 평가 시스템 아키텍처.ipynb](./위험도%20평가%20시스템%20아키텍처.ipynb) | **여기부터**  가설 6개, 버전 진화, 핵심 실험 기록 |
| [모델정보.ipynb](./모델정보.ipynb) | 최종 시스템 설명서 (데이터, 모델, 하이퍼파라미터, 파이프라인 전체) |
| [버전6.ipynb](./버전6.ipynb) | v6 "신뢰 구간만 말하기"  H6 확장, V5 대비 실측 비교 |
| [데이터탐색.ipynb](./데이터탐색.ipynb) | EDA  클래스 분포 (Lane Mark 0.6% 병목), 도메인 특성 |

> ⚠️ 노트북 용량이 커서 GitHub 렌더링이 느릴 수 있습니다. [nbviewer](https://nbviewer.org/)에 URL을 붙여 넣으면 안정적으로 열립니다.

**데이터**: Kaggle  Motorcycle Night Ride Segmentation (200장, 7-class semantic segmentation)
