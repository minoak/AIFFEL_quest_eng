"""
geometric_distance.py — Camera calibration 없이 pixel → meter 거리 추정

3개 estimator 다수결:
    1. d_ground  — bbox 바닥 y 좌표 기반 (ground plane)
    2. d_size    — bbox 폭 + 차종 prior (1.8m / 2.5m / 0.8m)
    3. d_depth   — Depth Anything V2 output 을 α·(1/depth)+β 로 fit

핵심 트릭: 한국 차선폭 = 3.5m prior 로 focal length f 역산.
(Mobileye Gen 1 방식, OpenPilot/Apollo 도 사용 중)

사용:
    from geometric_distance import DistanceEstimator
    est = DistanceEstimator()
    est.estimate_focal(lanes_detected, vp_y, img_h)   # session 시작 시 1회
    d_info = est.estimate_object(bbox, class_name, depth_map, vp_y, img_h)
    # d_info = {'d_fused_m', 'd_bin', 'confidence', 'breakdown'}
"""
from __future__ import annotations
import numpy as np
from typing import Dict, List, Optional, Tuple


# ==================================================================
# 상수 (prior)
# ==================================================================

# 한국 도로 표준 (도로교통법 시행규칙)
LANE_WIDTH_M = 3.5

# 오토바이 블랙박스 카메라 높이 (approx)
CAMERA_HEIGHT_M = 1.0

# Default focal — 이미지 너비 기반 동적 (FoV ≈ 70° 가정)
# f = (W/2) / tan(FoV/2) = W/2 / tan(35°) ≈ W * 0.71
# 블랙박스는 보통 광각이라 f/W ≈ 0.6~0.8 범위
DEFAULT_FOCAL_RATIO = 1.2  # f_default = img_w * 1.2 (dashcam 낮은 FoV 가정)

# 객체 class 별 실제 폭 (meter)
# class_id: 4 Moveable (generic) — 승용차로 가정이 보편
# 세부 class 는 bbox aspect ratio 로 rough 분류 가능 (future)
OBJECT_WIDTH_M = {
    'moveable': 1.8,     # 승용차 default
    'car':      1.8,
    'truck':    2.5,
    'bus':      2.55,
    'motorcycle': 0.8,
    'bicycle':  0.6,
    'person':   0.5,
}

# 거리 bin (2+ estimator 합의 기준)
DISTANCE_BINS = [(0, 5), (5, 15), (15, 30), (30, float('inf'))]
DISTANCE_BIN_NAMES = ['<5m', '5-15m', '15-30m', '>30m']

# Estimator 가중치
# - DA V2 (non-metric): depth weight 낮게 (0.05, 야간 noise)
# - Depth Pro (metric): depth weight 높게 (0.5, 신뢰 가능)
ESTIMATOR_WEIGHTS = {
    'ground': 0.55,
    'size':   0.40,
    'depth':  0.05,
}
ESTIMATOR_WEIGHTS_METRIC = {
    'ground': 0.25,  # Depth Pro 가 ground plane 역할 흡수
    'size':   0.25,
    'depth':  0.50,  # metric 이라 primary
}


# ==================================================================
# Focal length 역산 — 차선폭 prior 활용
# ==================================================================

def estimate_focal_from_lanes(
    lanes: List[Dict],
    vp_y: float,
    img_w: int,
    img_h: int,
    min_sample_count: int = 2,
) -> Optional[float]:
    """차선폭 3.5m prior 로 focal length f (pixel) 역산.

    핵심 원리:
        서로 다른 y 좌표에서 좌/우 차선 pixel 간격을 측정.
        d ∝ 1/(y - vp_y), lane_width_px ∝ 1/d
        → lane_width_px * (y - vp_y) = const
        const = f * LANE_WIDTH_M / CAMERA_HEIGHT_M
        → f = const * CAMERA_HEIGHT_M / LANE_WIDTH_M

    Args:
        lanes: detect_lane_lines() 결과. 각 line = {dydx, c, y_top, y_bot, length, ...}
               x = dydx * y + c
        vp_y: vanishing point y 좌표
        img_w, img_h: 이미지 크기

    Returns:
        f_px (float) or None if estimation fails.
    """
    if len(lanes) < 2:
        return None

    # 전제: VP 가 이미지 중앙 근처 (30%~70% 가로) 일 때만 f 역산 시도
    # 커브길/기울어짐 케이스는 이 공식 성립 X
    cx = img_w / 2
    if abs(vp_x_from_lanes(lanes, img_w, img_h, vp_y) - cx) > img_w * 0.2:
        return None  # VP 가 중앙에서 너무 멀면 포기

    # Sort by x at bottom (y=img_h*0.9)
    y_sample = img_h * 0.9
    left_lane = None
    right_lane = None
    for l in lanes:
        x_sample = l['dydx'] * y_sample + l['c']
        if x_sample < cx - 20:
            if left_lane is None or abs(x_sample - cx) < abs(left_lane['dydx'] * y_sample + left_lane['c'] - cx):
                left_lane = l
        elif x_sample > cx + 20:
            if right_lane is None or abs(x_sample - cx) < abs(right_lane['dydx'] * y_sample + right_lane['c'] - cx):
                right_lane = l

    if left_lane is None or right_lane is None:
        return None

    # 추가 체크: y_bot 에서 xl < xr 이어야 함 (뒤집힘 방지)
    y_check = img_h * 0.9
    xl_check = left_lane['dydx'] * y_check + left_lane['c']
    xr_check = right_lane['dydx'] * y_check + right_lane['c']
    if xl_check >= xr_check:
        return None

    # 여러 y 샘플에서 const 계산 → median (robust)
    consts = []
    for y_frac in (0.75, 0.85, 0.95):
        y = img_h * y_frac
        if y <= vp_y + 20: continue
        x_left = left_lane['dydx'] * y + left_lane['c']
        x_right = right_lane['dydx'] * y + right_lane['c']
        w_px = x_right - x_left
        # 이미지 경계 내 + 양수 width
        if w_px < 20: continue
        if x_left < -img_w * 0.5 or x_right > img_w * 1.5: continue
        const = w_px * (y - vp_y)
        if const <= 0: continue
        consts.append(const)

    if len(consts) < min_sample_count:
        return None

    const = float(np.median(consts))
    f_px = const * CAMERA_HEIGHT_M / LANE_WIDTH_M

    # Sanity check: 이미지 너비 대비 0.3 ~ 2.0 범위
    if not (img_w * 0.3 < f_px < img_w * 2.5):
        return None

    return float(f_px)


def vp_x_from_lanes(lanes, img_w, img_h, vp_y):
    """주어진 lines 의 x 위치에서 VP x 를 근사.
    lanes 의 평균적 수렴점."""
    if len(lanes) < 2:
        return img_w / 2
    # 간단히: 각 line 이 vp_y 에서 갖는 x
    xs = [l['dydx'] * vp_y + l['c'] for l in lanes]
    return float(np.median(xs))


# ==================================================================
# Estimator 1: Ground plane (bbox bottom y → distance)
# ==================================================================

def distance_from_ground(
    bbox: Tuple[int, int, int, int],
    vp_y: float,
    f_px: float,
    camera_h: float = CAMERA_HEIGHT_M,
) -> Optional[float]:
    """bbox 바닥 y 좌표로 ground plane 교점 거리.

    공식: d = f_px * camera_h / (y_bottom - vp_y)
    전제: flat ground + 객체가 지면 위에 있음.
    """
    x0, y0, x1, y1 = bbox
    dy = y1 - vp_y
    if dy <= 5:  # VP 위쪽 or 너무 가까움 → 무한대
        return None
    d = f_px * camera_h / dy
    # Sanity: 0.5m ~ 200m
    if not (0.5 < d < 200):
        return None
    return float(d)


# ==================================================================
# Estimator 2: Size prior (bbox width → distance)
# ==================================================================

def classify_object(bbox: Tuple[int, int, int, int], class_id: int) -> str:
    """Aspect ratio + size 로 coarse 분류. DLthon class_id 4 Moveable 만 들어옴.

    aspect = w/h:
        매우 넓음 (>2.5): 버스/트럭
        보통 (1.3~2.5): 승용차
        세로 우세 (<0.8): 오토바이/사람
    """
    x0, y0, x1, y1 = bbox
    w = max(x1 - x0, 1)
    h = max(y1 - y0, 1)
    ar = w / h

    if class_id == 5:   # My bike
        return 'motorcycle'
    if class_id == 6:   # Rider
        return 'person'

    # Moveable (class 4) sub-classify
    if ar > 2.5:
        return 'truck'  # 버스도 폭 비슷
    elif ar > 1.2:
        return 'car'
    elif ar > 0.7:
        return 'car'    # 약간 비스듬한 차
    else:
        return 'motorcycle'


def distance_from_size(
    bbox: Tuple[int, int, int, int],
    obj_class: str,
    f_px: float,
) -> Optional[float]:
    """bbox 폭 + 차종 prior 로 거리.

    공식: d = f_px * W_real / w_bbox_px
    """
    x0, y0, x1, y1 = bbox
    w_px = max(x1 - x0, 1)
    W_real = OBJECT_WIDTH_M.get(obj_class, 1.8)
    d = f_px * W_real / w_px
    if not (0.5 < d < 200):
        return None
    return float(d)


# ==================================================================
# Estimator 3: Depth map → metric (α, β fit)
# ==================================================================

def distance_from_depth(
    depth_map: np.ndarray,
    bbox: Tuple[int, int, int, int],
    alpha: float = 30.0,
    beta: float = 0.0,
    pct: int = 90,
    is_metric: bool = False,
) -> Optional[float]:
    """Depth → metric 거리.

    is_metric=False (DA V2): inverse depth 0-255, α/depth+β 변환.
    is_metric=True (Depth Pro): meter 단위 직접. bbox 의 **10th percentile** (가까운 면) 사용.
    """
    x0, y0, x1, y1 = bbox
    patch = depth_map[y0:y1+1, x0:x1+1]
    if patch.size == 0:
        return None

    if is_metric:
        # Metric depth (meter). bbox 의 median 을 대표 거리로
        # (10th percentile 은 bbox 가장자리/occlusion 때문에 과도하게 짧게 나옴)
        valid = patch[(patch > 0.3) & (patch < 100)]
        if valid.size < 5:
            return None
        d = float(np.median(valid))
        if not (0.3 < d < 100):
            return None
        return d

    # DA V2 legacy path
    p = float(np.percentile(patch, pct)) / 255.0
    if p < 0.05:
        return None
    d = alpha / p + beta
    if not (0.5 < d < 200):
        return None
    return float(d)


# ==================================================================
# Fusion — weighted median + consensus
# ==================================================================

def fuse_distances(
    estimates: Dict[str, Optional[float]],
    weights: Dict[str, float] = None,
    depth_is_metric: bool = False,
) -> Dict:
    """3 estimator 결과 fusion.

    Args:
        estimates: {'ground': d_g, 'size': d_s, 'depth': d_d}, None 허용
        weights: 기본 ESTIMATOR_WEIGHTS

    Returns:
        {
            'd_fused_m': float or None,
            'd_bin': str ('<5m' etc),
            'd_bin_idx': int (0-3),
            'confidence': 'high' / 'medium' / 'low' / 'none',
            'n_valid': int,
            'estimates': {'ground': ..., 'size': ..., 'depth': ...},
        }
    """
    if weights is None:
        weights = ESTIMATOR_WEIGHTS_METRIC if depth_is_metric else ESTIMATOR_WEIGHTS

    valid = {k: v for k, v in estimates.items() if v is not None}
    n_valid = len(valid)

    if n_valid == 0:
        return {
            'd_fused_m': None,
            'd_bin': 'unknown',
            'd_bin_idx': -1,
            'confidence': 'none',
            'n_valid': 0,
            'estimates': estimates,
        }

    # 1. Outlier rejection: median 의 3배 밖
    values = list(valid.values())
    med = float(np.median(values))
    filtered = {k: v for k, v in valid.items() if 0.33 * med < v < 3.0 * med}
    if len(filtered) == 0:
        # 전부 outlier → median 그대로 쓰되 confidence low
        filtered = valid

    # 2. Weighted mean on filtered
    total_w = sum(weights[k] for k in filtered)
    d_fused = sum(filtered[k] * weights[k] / total_w for k in filtered)

    # 3. Bin
    d_bin_idx = 3
    for i, (lo, hi) in enumerate(DISTANCE_BINS):
        if lo <= d_fused < hi:
            d_bin_idx = i
            break
    d_bin = DISTANCE_BIN_NAMES[d_bin_idx]

    # 4. Confidence: 몇 개 estimator 가 같은 bin 에 합의했나
    bins_agreed = set()
    for k, v in valid.items():
        for i, (lo, hi) in enumerate(DISTANCE_BINS):
            if lo <= v < hi:
                bins_agreed.add(i)
                break

    if n_valid >= 3 and len(bins_agreed) == 1:
        conf = 'high'
    elif n_valid >= 2 and d_bin_idx in bins_agreed:
        conf = 'medium'
    elif n_valid >= 1:
        conf = 'low'
    else:
        conf = 'none'

    return {
        'd_fused_m': round(d_fused, 2),
        'd_bin': d_bin,
        'd_bin_idx': d_bin_idx,
        'confidence': conf,
        'n_valid': n_valid,
        'estimates': {k: round(v, 2) if v else None for k, v in estimates.items()},
    }


# ==================================================================
# 통합 클래스
# ==================================================================

class DistanceEstimator:
    """3-estimator fusion 거리 추정기.

    사용법:
        est = DistanceEstimator(depth_is_metric=True)  # Depth Pro 쓸 때
        est.f_px = 1022   # Depth Pro focal 직접 주입 (calibrate 대신)
        info = est.estimate(bbox, class_id, depth_map, vp_y)
    """

    def __init__(self, depth_is_metric: bool = False):
        self.f_px: Optional[float] = None
        self.camera_h: float = CAMERA_HEIGHT_M
        self.alpha: float = 30.0  # depth → metric α (DA V2 만 사용)
        self.beta: float = 0.0
        self.depth_is_metric: bool = depth_is_metric

    def calibrate(self, lanes: List[Dict], vp_y: float, img_w: int, img_h: int) -> bool:
        """Session 시작 또는 매 프레임 시작에 f 역산 시도.

        Returns: True if calibration succeeded.
        """
        f = estimate_focal_from_lanes(lanes, vp_y, img_w, img_h)
        if f is None:
            # 이미지 너비 기반 default
            self.f_px = img_w * DEFAULT_FOCAL_RATIO
            return False
        self.f_px = f
        return True

    def calibrate_depth_alpha(
        self,
        depth_map: np.ndarray,
        moveables: List[Dict],
        vp_y: float,
    ):
        """Depth Anything α,β 를 d_ground 로 fit (같은 프레임 내).
        Depth Pro (metric) 쓸 때는 skip.
        """
        if self.depth_is_metric:
            return  # metric 이면 불필요
        if self.f_px is None or len(moveables) < 2:
            return
        pts = []
        for o in moveables:
            d_g = distance_from_ground(o['bbox'], vp_y, self.f_px, self.camera_h)
            if d_g is None: continue
            x0, y0, x1, y1 = o['bbox']
            patch = depth_map[y0:y1+1, x0:x1+1]
            if patch.size == 0: continue
            p = float(np.percentile(patch, 90)) / 255.0
            if p < 0.05: continue
            pts.append((1.0 / p, d_g))
        if len(pts) < 2:
            return
        # Linear fit: d = α * (1/p) + β
        X = np.array([p[0] for p in pts])
        Y = np.array([p[1] for p in pts])
        try:
            alpha, beta = np.polyfit(X, Y, 1)
            if 1 < alpha < 200:  # sanity
                self.alpha = float(alpha)
                self.beta = float(beta)
        except Exception:
            pass

    def estimate(
        self,
        bbox: Tuple[int, int, int, int],
        class_id: int,
        depth_map: Optional[np.ndarray],
        vp_y: float,
    ) -> Dict:
        """단일 객체 거리 estimate."""
        if self.f_px is None:
            self.f_px = DEFAULT_FOCAL_PX

        obj_class = classify_object(bbox, class_id)

        d_ground = distance_from_ground(bbox, vp_y, self.f_px, self.camera_h)
        d_size = distance_from_size(bbox, obj_class, self.f_px)
        d_depth = None
        if depth_map is not None:
            d_depth = distance_from_depth(depth_map, bbox, self.alpha, self.beta,
                                          is_metric=self.depth_is_metric)

        fused = fuse_distances({
            'ground': d_ground,
            'size': d_size,
            'depth': d_depth,
        }, depth_is_metric=self.depth_is_metric)
        fused['obj_class'] = obj_class
        return fused


# ==================================================================
# Self-test
# ==================================================================

if __name__ == '__main__':
    # Fake lanes
    lanes = [
        {'dydx': -0.3, 'c': 600, 'y_top': 300, 'y_bot': 900, 'length': 400},
        {'dydx':  0.3, 'c': 1200, 'y_top': 300, 'y_bot': 900, 'length': 400},
    ]
    est = DistanceEstimator()
    ok = est.calibrate(lanes, vp_y=400, img_w=1920, img_h=1080)
    print(f'Calibration: {ok}, f_px = {est.f_px:.1f}')

    # Fake bbox (승용차 크기, 중간 거리)
    bbox = (800, 600, 1000, 750)
    info = est.estimate(bbox, class_id=4, depth_map=None, vp_y=400)
    print(f'Estimate: {info}')
