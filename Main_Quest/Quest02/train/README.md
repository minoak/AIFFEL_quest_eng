# train/ — Lane Focus 5-fold 학습 재현

최종 세그멘테이션 모델 (U-Net R34, Lane Focus recipe) 의 학습 코드.
체크포인트 `lane_focus_fold0~4_best.pth` 가 이 코드로 만들어졌다.

## 레시피

- **모델**: U-Net (encoder ResNet34, ImageNet pretrained) — `segmentation_models_pytorch`
- **Loss**: 0.3 Focal(γ=2) + 0.3 Dice + 0.4 WeightedCE (class_weight[3]=50 — Lane Mark)
- **Lane Mark GT 두께화**: morphology dilation 5px (train 만, val 은 원본 GT)
- **해상도 768×768, BS 4, 40 epochs, AdamW lr 1e-4, cosine, seed 42**
- 결과: mIoU(fg) **0.7845 ± 0.0100**, Lane Mark IoU 0.3611 ± 0.0245 (5-fold, per-fold best 평균 — `lane_focus_5fold_results.json` 실측값)

## 파일

| 파일 | 내용 |
|---|---|
| `preprocessing.ipynb` | Kaggle 데이터 → raster mask 200장 + split 생성 (한 번만 실행) |
| `dataset.py` | PyTorch Dataset + Albumentations 증강 모듈 |
| `train_lane_focus_5fold.ipynb` | **5-fold 학습 본체** (Lane Focus recipe) |
| `splits.json` | Test 30 / Dev 170 + 5-fold 인덱스 (재현용 고정 split, seed 42) |
| `class_mapping.json` | 데이터셋 내부 ID → 학습용 0~6 label 매핑 |
| `lane_focus_5fold_results.json` | 실제 학습 기록 (fold별 곡선 + 최종 지표) — README 수치의 근거 |
| `lv1_kfold_results.json` | baseline (Lv1) 5-fold 기록 — 학습 노트북의 비교 셀에서 사용 |

## 실행 순서

1. Kaggle 에서 **Motorcycle Night Ride Segmentation** 데이터셋을 받아
   이 폴더(`train/`) 아래에 압축 해제한다. 폴더명 그대로:
   `www.acmeai.tech ODataset 1 - Motorcycle Night Ride Dataset/` (안에 `images/` 200장 + COCO json)
2. `preprocessing.ipynb` 실행 → `masks/` 200장 생성.
   (`splits.json`·`class_mapping.json` 은 저장소에 포함되어 있고, 재실행해도 seed 42 로 동일하게 재생성된다)
3. `train_lane_focus_5fold.ipynb` 실행 → fold 별 best 체크포인트가 이 폴더에 저장된다.
   실측 fold당 13~16분 (원 실험 GPU 기준, `lane_focus_5fold_results.json` 의 `time_min`).

이미 학습된 체크포인트를 바로 쓰려면 상위 README 의 **체크포인트** 항목 참고.

## 알려진 동작 노트 (재현 정확성)

`dataset.py` 와 학습 노트북의 `A.GaussNoise(var_limit=...)` 인자는 albumentations 2.x 에서
유효하지 않아 **무시되고 기본 노이즈 강도로 적용**된다 (실행 시 UserWarning).
원 학습 당시에도 동일 조건이었음이 당시 노트북 출력으로 확인되어 (체크포인트가 이 상태로 학습됨),
코드를 수정하지 않고 그대로 두었다.
