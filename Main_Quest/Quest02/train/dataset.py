"""
DL-thon 데이터 모듈: Motorcycle Night Ride Segmentation

preprocessing.ipynb의 산출물(masks, splits.json, class_mapping.json)을 읽어
PyTorch Dataset + Albumentations 증강을 제공하는 재사용 모듈.

사용 예:
    import dataset as ds

    train_ds, val_ds = ds.get_fold_datasets(fold=0, img_size=512)
    test_ds = ds.get_test_dataset(img_size=512)

단독 실행 (sanity check):
    python dataset.py
"""
from pathlib import Path
import json
import numpy as np
from PIL import Image
import torch
from torch.utils.data import Dataset
import albumentations as A
from albumentations.pytorch import ToTensorV2


# ====== 경로 상수 ======
# 이 파일(train/)이 있는 폴더 기준. Kaggle 데이터셋 폴더를 같은 위치에 풀어 둔다.
BASE = Path(__file__).resolve().parent
IMG_DIR = BASE / 'www.acmeai.tech ODataset 1 - Motorcycle Night Ride Dataset' / 'images'
MASKS_DIR = BASE / 'masks'
SPLITS_PATH = BASE / 'splits.json'
CLASS_MAP_PATH = BASE / 'class_mapping.json'

# ====== 학습 상수 ======
NUM_CLASSES = 7                                  # 0=Background + 6 클래스
IMAGENET_MEAN = [0.485, 0.456, 0.406]
IMAGENET_STD = [0.229, 0.224, 0.225]


# ====== 유틸 ======
def load_splits():
    with open(SPLITS_PATH, encoding='utf-8') as f:
        return json.load(f)


def load_class_map():
    with open(CLASS_MAP_PATH, encoding='utf-8') as f:
        return json.load(f)


# ====== Dataset ======
class MotorcycleDataset(Dataset):
    """
    image_ids: splits.json의 image_id 리스트
    transform: Albumentations Compose (이미지+마스크 동시 적용)
    """
    def __init__(self, image_ids, transform=None):
        splits = load_splits()
        id_to_file = splits['image_id_to_file_name']
        self.items = [
            {'image_id': iid, 'file_name': id_to_file[str(iid)]}
            for iid in image_ids
        ]
        self.transform = transform

    def __len__(self):
        return len(self.items)

    def __getitem__(self, idx):
        item = self.items[idx]
        img = np.array(Image.open(IMG_DIR / item['file_name']).convert('RGB'))
        mask = np.array(Image.open(MASKS_DIR / item['file_name']))  # uint8, (H,W)

        if self.transform is not None:
            out = self.transform(image=img, mask=mask)
            img, mask = out['image'], out['mask']

        if isinstance(mask, torch.Tensor):
            mask = mask.long()  # CE Loss는 LongTensor label 요구
        return img, mask


# ====== Transform 팩토리 ======
def get_train_transform(size=512, aug=True):
    """학습용 transform.

    aug=False → resize + 정규화만. 베이스라인 검증용 (증강 효과를 배제한 원본 성능).
    aug=True  → HFlip + Brightness + CLAHE + GaussNoise. Day 2 실험부터 사용.
    """
    if not aug:
        return A.Compose([
            A.Resize(size, size),
            A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
            ToTensorV2(),
        ])
    return A.Compose([
        A.Resize(size, size),
        A.HorizontalFlip(p=0.5),
        A.RandomBrightnessContrast(brightness_limit=0.2, contrast_limit=0.2, p=0.5),
        A.CLAHE(clip_limit=4.0, p=0.3),                     # 야간 히스토그램 보정
        A.GaussNoise(var_limit=(10.0, 50.0), p=0.2),
        A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ToTensorV2(),
    ])


def get_val_transform(size=512):
    """검증/테스트용: resize + 정규화만."""
    return A.Compose([
        A.Resize(size, size),
        A.Normalize(mean=IMAGENET_MEAN, std=IMAGENET_STD),
        ToTensorV2(),
    ])


# ====== 편의 함수 ======
def get_fold_datasets(fold=0, img_size=512, train_aug=True):
    """fold 번호를 받아 (train_ds, val_ds) 반환.

    train_aug=False로 호출하면 train도 증강 없이 구성 (베이스라인용).
    """
    splits = load_splits()
    assert 0 <= fold < splits['n_folds'], f'fold는 0~{splits["n_folds"]-1}'
    fd = splits['folds'][fold]
    train_ds = MotorcycleDataset(fd['train_image_ids'], transform=get_train_transform(img_size, aug=train_aug))
    val_ds = MotorcycleDataset(fd['val_image_ids'], transform=get_val_transform(img_size))
    return train_ds, val_ds


def get_test_dataset(img_size=512):
    splits = load_splits()
    return MotorcycleDataset(splits['test_image_ids'], transform=get_val_transform(img_size))


def denormalize(img_tensor):
    """정규화된 텐서(C,H,W)를 시각화 가능한 numpy(H,W,C) [0,1]로."""
    mean = torch.tensor(IMAGENET_MEAN).view(3, 1, 1)
    std = torch.tensor(IMAGENET_STD).view(3, 1, 1)
    out = img_tensor.detach().cpu() * std + mean
    return out.permute(1, 2, 0).clamp(0, 1).numpy()


# ====== 단독 실행: sanity check ======
if __name__ == '__main__':
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    plt.rcParams['font.family'] = 'Malgun Gothic'
    plt.rcParams['axes.unicode_minus'] = False

    class_map = load_class_map()
    label_to_name = {int(k): v for k, v in class_map['label_to_name'].items()}

    train_ds, val_ds = get_fold_datasets(fold=0, img_size=512)
    test_ds = get_test_dataset(img_size=512)
    print(f'Train: {len(train_ds)}장')
    print(f'Val  : {len(val_ds)}장')
    print(f'Test : {len(test_ds)}장')
    print()

    img, mask = train_ds[0]
    print(f'Image tensor: shape={tuple(img.shape)}, dtype={img.dtype}, range=[{img.min():.2f}, {img.max():.2f}]')
    print(f'Mask tensor : shape={tuple(mask.shape)}, dtype={mask.dtype}, unique={torch.unique(mask).tolist()}')

    # 증강이 제대로 붙었는지 시각화 (같은 샘플을 여러 번 → 변형 확인)
    palette = plt.cm.tab10(np.linspace(0, 0.9, NUM_CLASSES))[:, :3]
    palette[0] = [0.1, 0.1, 0.1]

    fig, axes = plt.subplots(3, 2, figsize=(12, 12))
    for row in range(3):
        img_t, mask_t = train_ds[0]                      
        img_vis = denormalize(img_t)
        mask_vis = palette[mask_t.numpy()]
        axes[row, 0].imshow(img_vis); axes[row, 0].set_title(f'증강 샘플 #{row+1}  (train_ds[0])'); axes[row, 0].axis('off')
        axes[row, 1].imshow(mask_vis); axes[row, 1].set_title(f'마스크  unique={sorted(torch.unique(mask_t).tolist())}'); axes[row, 1].axis('off')

    legend_handles = [mpatches.Patch(color=palette[i], label=f'{i}: {label_to_name[i]}') for i in range(NUM_CLASSES)]
    fig.legend(handles=legend_handles, loc='lower center', ncol=NUM_CLASSES, bbox_to_anchor=(0.5, -0.01))
    plt.tight_layout()
    plt.savefig(BASE / 'dataset_sanity_check.png', dpi=100, bbox_inches='tight')
    plt.show()
    print(f'\n시각화 저장: dataset_sanity_check.png')
