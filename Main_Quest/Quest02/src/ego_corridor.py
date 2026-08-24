"""
ego_corridor.py — VP + ego_lane 기반 4-zone 사다리꼴 corridor 생성 및 bbox zone 분류.

설계 (Mobileye/OpenPilot 등 업계 관행 리서치 수렴):
    - 전략: Clamp/additive layer (v5 유지, zone 은 보정)
    - Bbox foot-point (bottom-center) 가 노면 접지점
    - Lane-width 정규화된 signed distance (해상도 불변)
    - 4 nested zone: critical / danger / caution / sidelobe (BSW)

핵심 공식:
    y = vp_y + alpha * (H - vp_y)   # parametric (해상도 독립)
    x = vp_x + (y - vp_y) / (H - vp_y) * (x_bottom - vp_x)  # lane 보간

Safeguards:
    - VP confidence < 0.3 → corridor 사용 불가 (None 반환)
    - Frame 3 갓길 regression 방지: LDW 활성 frame 은 호출측에서 zone confirmation 비활성
    - Moveable (class 4) 만 체크

사용:
    from ego_corridor import build_corridor, classify_zone
    corridor = build_corridor(vp_x, vp_y, L_b, R_b, H, W)
    if corridor is None:   # VP 신뢰도 낮음
        ...  # zone 기능 disable
    for o in moveables:
        sev, info = classify_zone(o['bbox'], corridor)
        o['zone_sev'] = sev
        o['zone_info'] = info
"""
from __future__ import annotations
import numpy as np
import cv2
from typing import Dict, Optional, Tuple


# ==========================================================
# Zone 기하 — alpha 비율 (VP 에서 bottom 방향)
# ==========================================================
DEFAULT_ALPHAS = {
    'critical': 0.85,   # 하위 15% (내 차선 바로 앞 치명 zone)
    'danger':   0.55,   # 하위 45% (FCW L2 수준)
    'caution':  0.15,   # 하위 85% (전체 ego corridor)
}
SIDE_EXPAND = 0.30      # sidelobe: corridor 를 좌/우로 확장하는 비율


def _y_at(vp_y: float, alpha: float, H: int) -> float:
    """VP 에서 bottom 까지 alpha 비율 지점의 y 좌표."""
    return vp_y + alpha * (H - 1 - vp_y)


def _lane_x_at(vp_x: float, vp_y: float, x_bottom: float, H: int, y: float) -> float:
    """VP 에서 bottom 의 x 까지 line 의 y 지점 x 좌표."""
    denom = max(H - 1 - vp_y, 1e-6)
    t = (y - vp_y) / denom
    return vp_x + t * (x_bottom - vp_x)


# ==========================================================
# Corridor 생성
# ==========================================================
def build_corridor(
    vp_x: int, vp_y: int,
    x_left_bottom: float, x_right_bottom: float,
    H: int, W: int,
    vp_conf: float = 1.0,
    alphas: Dict[str, float] = None,
    side_expand: float = SIDE_EXPAND,
) -> Optional[Dict]:
    """VP + ego_lane 하단 교차점으로 4-zone nested polygon 생성.

    Args:
        vp_x, vp_y: vanishing point
        x_left_bottom, x_right_bottom: ego_lane 좌/우 line 이 y=H-1 에서 갖는 x
        H, W: image size
        vp_conf: VP confidence (0~1). 0.3 미만이면 None 반환 (safeguard)
        alphas: {'critical': 0.85, 'danger': 0.55, 'caution': 0.15}
        side_expand: sidelobe 확장 비율

    Returns:
        dict with keys:
            'polygons': {'critical', 'danger', 'caution',
                         'sidelobe_left', 'sidelobe_right'} → np.array of shape (N, 2)
            'masks': 각 polygon 의 (H, W) uint8 mask (빠른 IoU 계산용)
            'vp': (vp_x, vp_y)
            'lane_width_at': function (y) → width
        None if vp_conf < 0.3
    """
    if vp_conf < 0.3:
        return None
    if alphas is None:
        alphas = DEFAULT_ALPHAS

    y_bot = H - 1
    Lx, Rx = x_left_bottom, x_right_bottom

    if Rx - Lx < 20:  # lane width 이상 (뒤집힘 등)
        return None

    def trapezoid(alpha_top):
        yt = _y_at(vp_y, alpha_top, H)
        xtl = _lane_x_at(vp_x, vp_y, Lx, H, yt)
        xtr = _lane_x_at(vp_x, vp_y, Rx, H, yt)
        # 시계 방향: top-left, top-right, bottom-right, bottom-left
        return np.array([
            [xtl, yt], [xtr, yt],
            [Rx, y_bot], [Lx, y_bot]
        ], dtype=np.int32)

    polys = {
        'critical': trapezoid(alphas['critical']),
        'danger':   trapezoid(alphas['danger']),
        'caution':  trapezoid(alphas['caution']),
    }

    # Sidelobe: 차선 폭 × side_expand 만큼 좌/우 확장 — BSW 용
    lane_w_bot = Rx - Lx
    dx = side_expand * lane_w_bot
    # Sidelobe 는 apex 가 VP, 바닥에서 Lx-dx ~ Lx (왼쪽) / Rx ~ Rx+dx (오른쪽)
    polys['sidelobe_left'] = np.array([
        [vp_x, vp_y], [Lx, y_bot], [Lx - dx, y_bot]
    ], dtype=np.int32)
    polys['sidelobe_right'] = np.array([
        [vp_x, vp_y], [Rx + dx, y_bot], [Rx, y_bot]
    ], dtype=np.int32)

    # 빠른 IoU 를 위해 mask 미리 생성 (frame 당 5 masks)
    masks = {}
    for name, poly in polys.items():
        m = np.zeros((H, W), dtype=np.uint8)
        cv2.fillPoly(m, [poly], 1)
        masks[name] = m

    def lane_width_at(y):
        xl = _lane_x_at(vp_x, vp_y, Lx, H, y)
        xr = _lane_x_at(vp_x, vp_y, Rx, H, y)
        return max(xr - xl, 1.0)

    return {
        'polygons': polys,
        'masks': masks,
        'vp': (int(vp_x), int(vp_y)),
        'lane_bottom': (int(Lx), int(Rx)),
        'lane_width_at': lane_width_at,
        'alphas': alphas,
    }


# ==========================================================
# Bbox → Zone 분류
# ==========================================================
def classify_zone(
    bbox: Tuple[int, int, int, int],
    corridor: Optional[Dict],
    soft_promote_ratio: float = 0.30,
) -> Tuple[int, Dict]:
    """Bbox 를 zone severity (0~3) 로 분류.

    로직:
        1. Anchor = bbox bottom-center (foot point)
        2. Foot 이 어느 zone 에 있나 결정 (inner 부터 순서대로)
        3. Soft promote: bbox 중 더 안쪽 zone 에 30%+ 겹치면 승급
        4. Sidelobe: 별도 신호 (BSW 용)

    Severity 매핑:
        0 = safe (zone 밖)
        1 = caution (전체 corridor 내부)
        2 = danger (중간 zone)
        3 = critical (inner zone, 치명)

    Returns:
        (severity: int, info: dict)
        info 에 anchor_zone, bbox_ratios, sidelobe_hit, in_corridor 포함
    """
    info = {
        'anchor_zone': 'safe',
        'bbox_ratios': {},
        'sidelobe_hit': None,
        'sidelobe_ratio': 0.0,
        'in_corridor': False,
    }
    if corridor is None:
        return 0, info

    x0, y0, x1, y1 = bbox
    H, W = corridor['masks']['critical'].shape

    # Foot point = bbox bottom-center
    foot_x = int((x0 + x1) / 2)
    foot_y = int(y1)
    foot_x = max(0, min(W - 1, foot_x))
    foot_y = max(0, min(H - 1, foot_y))

    # 1. Anchor (inner 부터 체크)
    anchor = 'safe'
    for name in ('critical', 'danger', 'caution'):
        if corridor['masks'][name][foot_y, foot_x] > 0:
            anchor = name
            break
    info['anchor_zone'] = anchor
    info['in_corridor'] = anchor != 'safe'

    # 2. Bbox IoU (bbox_ratio = intersection / bbox_area)
    bbox_area = max((x1 - x0) * (y1 - y0), 1)
    # Clip bbox to image
    cx0, cy0 = max(0, x0), max(0, y0)
    cx1, cy1 = min(W, x1), min(H, y1)
    if cx1 <= cx0 or cy1 <= cy0:
        return 0, info

    for name in ('critical', 'danger', 'caution',
                 'sidelobe_left', 'sidelobe_right'):
        patch = corridor['masks'][name][cy0:cy1, cx0:cx1]
        inter = int(patch.sum())
        info['bbox_ratios'][name] = round(inter / bbox_area, 3)

    # 3. Severity 매핑
    sev_map = {'safe': 0, 'caution': 1, 'danger': 2, 'critical': 3}
    sev = sev_map[anchor]

    # Soft promote: bbox 의 더 안쪽 zone 에 30% 이상 걸치면 승급
    if info['bbox_ratios']['critical'] > soft_promote_ratio:
        sev = max(sev, 3)
    elif info['bbox_ratios']['danger'] > soft_promote_ratio:
        sev = max(sev, 2)
    elif info['bbox_ratios']['caution'] > soft_promote_ratio:
        sev = max(sev, 1)

    # 4. Sidelobe (BSW 전용 별도 신호)
    sl_max = max(info['bbox_ratios']['sidelobe_left'],
                 info['bbox_ratios']['sidelobe_right'])
    if sl_max > 0.40:  # 40% 이상이 sidelobe 안
        info['sidelobe_hit'] = ('left' if info['bbox_ratios']['sidelobe_left']
                                > info['bbox_ratios']['sidelobe_right'] else 'right')
        info['sidelobe_ratio'] = round(sl_max, 3)

    return sev, info


# ==========================================================
# Visualization helper
# ==========================================================
def draw_zones_on_ax(ax, corridor: Optional[Dict],
                     alpha: float = 0.15):
    """HUD 에 zone overlay 그리기. matplotlib axis 에 직접 fill."""
    if corridor is None: return
    import matplotlib.patches as mpatches

    zone_colors = {
        'critical':       ('red',    0.20),
        'danger':         ('orange', 0.15),
        'caution':        ('yellow', 0.08),
        'sidelobe_left':  ('blue',   0.08),
        'sidelobe_right': ('blue',   0.08),
    }

    # 순서: outer 먼저 → inner 나중에 (겹침 자연스럽게)
    draw_order = ['caution', 'danger', 'critical',
                  'sidelobe_left', 'sidelobe_right']
    for name in draw_order:
        if name not in corridor['polygons']: continue
        poly = corridor['polygons'][name]
        color, a = zone_colors[name]
        patch = mpatches.Polygon(poly, closed=True,
                                  facecolor=color, alpha=a,
                                  edgecolor=color, linewidth=0.8)
        ax.add_patch(patch)


# ==========================================================
# Self-test
# ==========================================================
if __name__ == '__main__':
    # Fake corridor
    H, W = 500, 500
    vp_x, vp_y = 250, 150
    Lx, Rx = 100, 400

    corridor = build_corridor(vp_x, vp_y, Lx, Rx, H, W, vp_conf=1.0)
    print(f'Corridor built: {list(corridor["polygons"].keys())}')

    # Test bboxes
    bboxes = [
        ('center-bottom (치명)', (200, 400, 300, 480)),
        ('left-edge (sidelobe)', (30, 400, 90, 480)),
        ('upper-corner (밖)', (0, 0, 50, 50)),
        ('mid-corridor (danger)', (180, 280, 320, 380)),
    ]
    for label, bb in bboxes:
        sev, info = classify_zone(bb, corridor)
        print(f'  {label} {bb}: sev={sev}, anchor={info["anchor_zone"]}, '
              f'ratios={info["bbox_ratios"]}, sidelobe={info["sidelobe_hit"]}')
