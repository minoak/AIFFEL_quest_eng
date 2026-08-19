"""hud_v5_clean.py — v5 위험도 평가 시스템의 깔끔한 HUD 시각화.

기존 draw_hud_v5 는 건드리지 않고 별도 구현. 발표용 정지 이미지 타깃.

## 사용법 (Jupyter / notebook)

    # 1회만: autoreload 활성화 + assessor 로 10장 재평가
    %load_ext autoreload
    %autoreload 2

    from pathlib import Path
    DOMAIN_DIR = Path(r'C:\\Users\\akals\\Downloads\\도메인 테스트')
    domain_paths = sorted(DOMAIN_DIR.glob('화면 캡처 2026-04-23 *.png'))

    results = {p.name: assessor.assess(p) for p in domain_paths}

    # 반복: style 수정 → 재렌더
    from hud_v5_clean import render_gallery, STYLE
    STYLE['show_zones'] = True         # 예: zone overlay 켜기
    render_gallery(domain_paths, results, save='v5_gallery_clean.png')

## 수정 팁

모든 시각 요소는 STYLE dict 에 상수로 노출되어 있습니다.
한 줄만 바꾸고 render_gallery() 재호출하면 10장 전부 즉시 다시 그려집니다.
"""
from __future__ import annotations
import re
from pathlib import Path
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch
from PIL import Image

_DIST_RE = re.compile(r'(\d+\.?\d*)\s*m')


def _distance_from_warning(w):
    """WarningResult 에서 거리(m) 추출. extra 우선, 없으면 reason 파싱."""
    extra = getattr(w, 'extra', None) or {}
    for key in ('distance_m', 'dist_m', 'd_m', 'distance'):
        v = extra.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                pass
    reason = getattr(w, 'reason', '') or ''
    m = _DIST_RE.search(reason)
    return float(m.group(1)) if m else None


# ============================================================
# STYLE — 여기만 수정하면 전체 룩 변경
# ============================================================
STYLE = {
    # ------- 전반 -------
    'font_family': 'Malgun Gothic',
    'font_size_sm': 8,
    'font_size_md': 10,
    'font_size_lg': 13,

    # ------- Bin 배지 (우상단 pill) -------
    'bin_badge_pos': 'top_right',       # 'top_right' | 'top_left'
    'bin_badge_margin': 0.018,          # 화면 여백 비율 (W, H 기준)
    'bin_show_top_warning': True,       # 배지에 top_warning 이름 같이 표시

    # ------- 활성 경고 chip 스택 (위험 상세 — 좌상단 독립 배치) -------
    'show_active_chips': True,          # 위험 요소 chip 세로 스택
    'chips_pos': 'top_left',            # 'top_left' | 'top_right' (bin 과 독립)
    'active_chips_show_reason': True,   # chip 에 한글 reason 포함
    'active_chips_reason_maxlen': 20,   # reason 너무 길면 자름
    'active_chips_gap': 0.010,          # chip 간 세로 간격 (H 비율)

    # ------- 경고 bbox -------
    'bbox_lw': 2.2,                     # 선 두께
    'bbox_lw_bonus_per_level': 0.7,     # severity 에 따라 추가
    'bbox_label_alpha': 0.92,
    'bbox_label_show_reason': True,     # 라벨에 한글 reason 포함
    'highlight_only_top_severity': True,  # 최고 심각도 bbox 만 강조, 나머지는 회색 통일

    # ------- 비경고 bbox (+ 최고 severity 외 경고 bbox) -------
    'other_bbox_show': True,
    'other_bbox_lw': 1.4,
    'other_bbox_alpha': 0.70,
    'other_bbox_color': '#b5b5b5',
    # zone_sev 기반 색 (비강조 bbox 에도 위험 수준 힌트)
    'zone_sev_colors': {
        3: '#E74C3C',    # critical — 연한 빨강
        2: '#E67E22',    # danger — 연한 주황
        1: '#F1C40F',    # caution — 노랑
        0: '#b5b5b5',    # safe — 회색
    },
    'sidelobe_color': '#3498DB',      # 측면 관측 — 파랑

    # ------- 거리 카드 (좌하단) -------
    'show_distance_card': True,
    'distance_card_alpha': 0.70,
    'distance_card_pad': 0.01,

    # ------- Ego lane band -------
    'show_lane_band': True,
    'lane_band_alpha': 0.12,
    'lane_line_alpha': 0.55,            # 차선 제대로 잡은 걸 확실히 보여줌
    'lane_line_lw': 1.6,

    # ------- 거리 태그 (bbox 하단 중앙 pill) -------
    'show_distance_tag': True,
    'distance_tag_bg': 'white',         # 흰 배경에 경고 색 글씨
    'distance_tag_alpha': 0.96,
    'distance_tag_outline': True,       # 경고 색 outline 유지

    # ------- 차선감지 실패 메시지 (우측하단, 부차 정보) -------
    'show_lane_fail_notice': True,
    'lane_fail_text': '⚠ 차선감지 실패',
    'lane_fail_color': '#7F8C8D',       # 중립 회색 (경고랑 헷갈리지 않게)

    # ------- Zone overlay (default OFF) -------
    'show_zones': False,
    'zone_alpha': 0.08,

    # ------- Debug / verbose (default OFF) -------
    'show_focal': False,                # 좌측하단 거리 카드 안에 병합
    'show_vp_dot': False,
    'show_fragment_count': False,

    # ------- YouTube mode (한문철 TV 스타일) -------
    'youtube_mode': True,                # True 시 상·하단 자막 bar + glow 적용
    'youtube_top_bar_height': 0.09,      # 상단 bin 배지 바 높이 (H 비율)
    'youtube_top_bar_alpha': 0.94,
    'youtube_top_font_size': 22,
    'youtube_bottom_bar_height': 0.075,  # 하단 해설 자막 바 높이
    'youtube_bottom_bar_alpha': 0.85,
    'youtube_bottom_font_size': 14,
    'youtube_glow_lw_multiplier': 2.5,   # 강조 bbox 외곽 glow 굵기 배수
    'youtube_glow_alpha': 0.30,
    'youtube_dist_tag_size': 14,         # 거리 pill 폰트 (유튜브 모드에서 더 큼)
    'youtube_emoji': True,                # 상단 배지에 ⚠️/🚨 이모지

    # ------- 색 팔레트 -------
    # Bin: 채도 약간 낮춘 버전
    'bin_colors': {
        '안전': '#27AE60',
        '주의': '#F39C12',
        '위험': '#E74C3C',
        '치명': '#8E44AD',
    },
    # Warning: 구별 유지하되 톤 맞춤
    'warning_colors': {
        'FCW':  '#E74C3C',   # 빨강 — 정면 충돌
        'LDW':  '#F1C40F',   # 노랑 — 차선 이탈
        'BSW':  '#E67E22',   # 주황 — 측면
        'HEAD': '#9B59B6',   # 보라 — 역주행
    },
}


# ============================================================
# 유틸
# ============================================================
def _font(S, size_key):
    return {'family': S['font_family'], 'size': S[size_key]}


def _pill(ax, x, y, text, color_bg, color_fg='white', size=10,
          ha='left', va='center', pad_x=6, pad_y=3, lw=0):
    """라운드 사각형 + 텍스트 (matplotlib text bbox 활용)."""
    ax.text(
        x, y, text,
        color=color_fg, fontsize=size, weight='bold', ha=ha, va=va,
        bbox=dict(boxstyle=f'round,pad=0.35',
                  facecolor=color_bg, edgecolor='none',
                  alpha=0.92, linewidth=lw),
        zorder=20,
    )


def _line_x_at(line, y):
    """line dict {dydx, c} 에서 y 에 해당하는 x."""
    return line['dydx'] * y + line['c']


# ============================================================
# 메인 draw 함수
# ============================================================
def draw_hud_v5_clean(ax, img, result, style=None):
    """HUD 를 matplotlib ax 에 깔끔 스타일로 그리기.

    Args:
        ax:      matplotlib Axes
        img:     (H, W, 3) RGB uint8
        result:  assessor.assess() 또는 assess_with_mask() 반환 dict
                 (_state, _ego, _corridor, _objs 내부 객체 필요)
        style:   STYLE 에 덮어쓸 partial dict. None 이면 기본 STYLE.
    """
    S = dict(STYLE)
    if style:
        S.update(style)

    H, W = img.shape[:2]
    ax.imshow(img)

    state = result.get('_state')
    ego = result.get('_ego', {}) or {}
    bin_ = result['bin']
    bin_color = S['bin_colors'][bin_]

    # ------------------------------
    # (선택) Zone overlay
    # ------------------------------
    if S['show_zones']:
        corridor = result.get('_corridor')
        if corridor is not None:
            try:
                # 기존 draw_zones_on_ax 가 있으면 alpha 를 조정해서 호출
                from __main__ import draw_zones_on_ax  # noqa
                draw_zones_on_ax(ax, corridor)
            except Exception:
                pass

    # ------------------------------
    # Ego lane band (얇은 outline + 연한 fill)
    # ------------------------------
    if S['show_lane_band'] and ego.get('left') and ego.get('right'):
        vp_y = result['vp']['y']
        y_top = max(vp_y, 0)
        ys = np.linspace(y_top, H, 30)
        xs_l = [_line_x_at(ego['left'], y) for y in ys]
        xs_r = [_line_x_at(ego['right'], y) for y in ys]

        # LDW 레벨에 따른 색
        ldw_lv = state.ldw.level if state else 0
        if ldw_lv == 2:
            lane_c = '#E74C3C'
        elif ldw_lv == 1:
            lane_c = '#F1C40F'
        else:
            lane_c = '#2ECC71'

        ax.fill_betweenx(ys, xs_l, xs_r, color=lane_c,
                         alpha=S['lane_band_alpha'], zorder=2)
        ax.plot(xs_l, ys, '-', color=lane_c,
                lw=S['lane_line_lw'], alpha=S['lane_line_alpha'], zorder=3)
        ax.plot(xs_r, ys, '-', color=lane_c,
                lw=S['lane_line_lw'], alpha=S['lane_line_alpha'], zorder=3)

    # ------------------------------
    # bbox 렌더링 — 최고 severity 만 강조, 나머지는 회색 통일
    # ------------------------------
    # 1. 최고 severity 찾기
    max_level = 0
    if state:
        for w in [state.fcw, state.ldw, state.bsw, state.head]:
            if w.level > max_level:
                max_level = w.level

    # 2. 강조 대상 bbox (최고 severity 의 warning bbox)
    highlight_bboxes = {}   # bbox_tuple -> warning
    if state and max_level > 0 and S['highlight_only_top_severity']:
        for w in [state.head, state.fcw, state.bsw]:
            if w.level == max_level and w.bbox is not None:
                key = tuple(w.bbox)
                if key not in highlight_bboxes:
                    highlight_bboxes[key] = w
    elif state and not S['highlight_only_top_severity']:
        # 기존 동작 — 모든 경고 bbox 강조
        for w in [state.head, state.fcw, state.bsw]:
            if w.level > 0 and w.bbox is not None:
                key = tuple(w.bbox)
                if key not in highlight_bboxes:
                    highlight_bboxes[key] = w

    # 3. 비강조 bbox — zone_sev 우선, 없으면 y-bottom (원근 거리) 기반 색
    if S['other_bbox_show']:
        zone_map = {tuple(z['bbox']): z
                    for z in result.get('per_obj_zones', [])}
        for o in result.get('_objs', []):
            key = tuple(o['bbox'])
            if key in highlight_bboxes:
                continue
            x0, y0, x1, y1 = o['bbox']
            zinfo = zone_map.get(key, {})
            sev = zinfo.get('zone_sev', 0)
            is_sidelobe = zinfo.get('sidelobe') is not None and zinfo.get('sidelobe') is not False

            if sev >= 1:
                c = S['zone_sev_colors'].get(sev, S['other_bbox_color'])
                lw = S['other_bbox_lw'] + 0.8
                alpha = 0.85
            elif is_sidelobe:
                c = S['sidelobe_color']
                lw = S['other_bbox_lw'] + 0.4
                alpha = 0.78
            else:
                # y-bottom 기반 fallback (원근 거리 힌트)
                y_rel = y1 / H
                if y_rel > 0.85:
                    c = '#E74C3C'   # 매우 근접
                    lw = S['other_bbox_lw'] + 0.8
                    alpha = 0.85
                elif y_rel > 0.70:
                    c = '#E67E22'   # 가까움
                    lw = S['other_bbox_lw'] + 0.4
                    alpha = 0.78
                elif y_rel > 0.55:
                    c = '#F1C40F'   # 중간 거리
                    lw = S['other_bbox_lw']
                    alpha = 0.70
                else:
                    c = S['other_bbox_color']   # 원거리 회색
                    lw = S['other_bbox_lw']
                    alpha = 0.55
            ax.add_patch(mpatches.Rectangle(
                (x0, y0), x1 - x0, y1 - y0,
                fill=False, edgecolor=c, linewidth=lw,
                alpha=alpha, zorder=4))

    # 4. 강조 bbox + 라벨 + 거리 태그
    youtube = S.get('youtube_mode', False)
    dist_size = S['youtube_dist_tag_size'] if youtube else S['font_size_md']

    for key, w in highlight_bboxes.items():
        x0, y0, x1, y1 = w.bbox
        c = S['warning_colors'][w.name]
        lw = S['bbox_lw'] + w.level * S['bbox_lw_bonus_per_level']

        # (glow) youtube_mode 시 외곽에 반투명 두꺼운 선 먼저
        if youtube:
            ax.add_patch(mpatches.Rectangle(
                (x0, y0), x1 - x0, y1 - y0,
                fill=False, edgecolor=c,
                linewidth=lw * S['youtube_glow_lw_multiplier'],
                alpha=S['youtube_glow_alpha'], zorder=5))

        ax.add_patch(mpatches.Rectangle(
            (x0, y0), x1 - x0, y1 - y0,
            fill=False, edgecolor=c, linewidth=lw, zorder=6))

        # (a) 상단 라벨 pill
        label = f'{w.name}·L{w.level}'
        _pill(ax, x0 + 2, max(y0 - 10, 14), label,
              color_bg=c, color_fg='white',
              size=S['font_size_sm'] if not youtube else 10,
              ha='left', va='center')

        # (b) 하단 거리 태그
        if S['show_distance_tag']:
            dist_m = _distance_from_warning(w)
            if dist_m is not None:
                cx = (x0 + x1) / 2
                ty = min(y1 + 14, H - 12)
                edge = c if S['distance_tag_outline'] else 'none'
                ax.text(
                    cx, ty, f'{dist_m:.1f}m',
                    color=c, fontsize=dist_size, weight='bold',
                    ha='center', va='center',
                    bbox=dict(
                        boxstyle='round,pad=0.40',
                        facecolor=S['distance_tag_bg'],
                        edgecolor=edge,
                        linewidth=1.6,
                        alpha=S['distance_tag_alpha'],
                    ),
                    zorder=8,
                )

    # ------------------------------
    # 거리 카드 (좌하단 소형) — focal 은 verbose 시 카드 오른쪽에 흐리게
    # (youtube_mode 에선 하단 자막 bar 와 겹쳐서 숨김)
    # ------------------------------
    pad = S['distance_card_pad']
    youtube_pre = S.get('youtube_mode', False)
    if S['show_distance_card'] and state and not youtube_pre:
        parts = []
        for label, d in [('정면', state.d_front_m),
                         ('좌', state.d_left_m),
                         ('우', state.d_right_m)]:
            parts.append(f'{label} {d:.1f}m' if d is not None else f'{label} —')
        text = '   '.join(parts)

        if S['show_focal'] and state.f_px:
            f_mark = '✓' if state.f_calibrated else '~'
            text = f'{text}   f={state.f_px:.0f}{f_mark}'

        ax.text(
            W * pad, H * (1 - pad), text,
            color='white', fontsize=S['font_size_md'], weight='bold',
            ha='left', va='bottom',
            bbox=dict(boxstyle='round,pad=0.45',
                      facecolor='black', edgecolor='none',
                      alpha=S['distance_card_alpha']),
            zorder=15,
        )

    # ------------------------------
    # 차선감지 실패 알림 (우측하단, 부차 정보)
    # ------------------------------
    if S['show_lane_fail_notice']:
        lane_ok = bool(ego.get('left') and ego.get('right'))
        ldw_reason = (state.ldw.reason if state and state.ldw else '') or ''
        lane_failed = (not lane_ok) or ('측정 불가' in ldw_reason)
        if lane_failed:
            ax.text(
                W * (1 - pad), H * (1 - pad),
                S['lane_fail_text'],
                color='white', fontsize=S['font_size_sm'], weight='bold',
                ha='right', va='bottom',
                bbox=dict(boxstyle='round,pad=0.45',
                          facecolor=S['lane_fail_color'],
                          edgecolor='none', alpha=0.80),
                zorder=15,
            )

    # ------------------------------
    # Bin 배지 (우상단 pill) — youtube_mode 에선 숨김 (상단 bar 로 대체)
    # ------------------------------
    youtube = S.get('youtube_mode', False)
    margin = S['bin_badge_margin']
    if S['bin_badge_pos'] == 'top_right':
        bx, ha = W * (1 - margin), 'right'
    else:
        bx, ha = W * margin, 'left'
    by = H * margin

    if not youtube:
        bin_text = f' {bin_} '
        if S['bin_show_top_warning'] and result.get('top_warning'):
            bin_text = f' {bin_} · {result["top_warning"]} '

        ax.text(
            bx, by, bin_text,
            color='white', fontsize=S['font_size_lg'], weight='bold',
            ha=ha, va='top',
            bbox=dict(boxstyle='round,pad=0.55',
                      facecolor=bin_color, edgecolor='white',
                      linewidth=1.2, alpha=0.95),
            zorder=25,
        )

    # ------------------------------
    # 활성 경고 chip 스택 — youtube_mode 에선 숨김 (하단 자막으로 대체)
    # ------------------------------
    if S['show_active_chips'] and state and not youtube:
        actives = [w for w in [state.fcw, state.ldw, state.bsw, state.head]
                   if w.level > 0]
        actives.sort(key=lambda w: (-w.level, w.name))

        chips_pos = S.get('chips_pos', 'top_left')
        if chips_pos == 'top_right':
            chips_x, chips_ha = W * (1 - margin), 'right'
        else:
            chips_x, chips_ha = W * margin, 'left'

        # 시작 y: bin 과 같은 쪽이면 bin pill 바로 아래, 다른 쪽이면 화면 최상단부터
        if chips_pos == S['bin_badge_pos']:
            y_cursor = by + H * 0.040
        else:
            y_cursor = H * margin

        gap = H * S['active_chips_gap']
        for w in actives:
            chip_color = S['warning_colors'][w.name]
            label = f'{w.name}·L{w.level}'
            if S['active_chips_show_reason'] and w.reason:
                reason = w.reason
                maxlen = S['active_chips_reason_maxlen']
                if len(reason) > maxlen:
                    reason = reason[:maxlen - 1] + '…'
                label = f'{label}  {reason}'
            ax.text(
                chips_x, y_cursor, label,
                color='white', fontsize=S['font_size_sm'], weight='bold',
                ha=chips_ha, va='top',
                bbox=dict(boxstyle='round,pad=0.40',
                          facecolor=chip_color, edgecolor='none',
                          alpha=0.90),
                zorder=24,
            )
            y_cursor += H * 0.028 + gap

    # ------------------------------
    # YouTube mode — 상단 bin bar + 하단 해설 자막 bar
    # ------------------------------
    if youtube:
        # --- 상단 bar (bin 색 배경, 큰 텍스트) ---
        top_h = H * S['youtube_top_bar_height']
        ax.add_patch(mpatches.Rectangle(
            (0, 0), W, top_h,
            facecolor=bin_color, edgecolor='white', linewidth=0,
            alpha=S['youtube_top_bar_alpha'], zorder=22))

        # 이모지
        emoji_map = {'안전': '✓', '주의': '⚠', '위험': '⚠', '치명': '🚨'}
        emoji = emoji_map.get(bin_, '') if S.get('youtube_emoji') else ''
        top_text = f'  {emoji}  {bin_}'
        if result.get('top_reason'):
            top_text += f'   —   {result["top_reason"]}'

        ax.text(
            W / 2, top_h / 2, top_text,
            color='white', fontsize=S['youtube_top_font_size'], weight='bold',
            ha='center', va='center', zorder=23,
        )

        # 좌측 상단에 작은 타임라벨 placeholder (seq_idx/time 있으면 표시)
        if result.get('time') or result.get('seq_idx'):
            seq = result.get('seq_idx', '')
            tm = result.get('time', '')
            label = f'#{seq:02d} · {tm}' if isinstance(seq, int) else str(tm)
            ax.text(
                W * 0.015, top_h / 2, label,
                color='white', fontsize=11, weight='bold',
                ha='left', va='center', zorder=24,
                bbox=dict(boxstyle='round,pad=0.25',
                          facecolor='black', edgecolor='none', alpha=0.45),
            )

        # --- 서브 bar: 위치별 거리 정보 (정면/좌/우) ---
        sub_h = H * 0.048
        ax.add_patch(mpatches.Rectangle(
            (0, top_h), W, sub_h,
            facecolor='#1a1a1a', edgecolor='none',
            alpha=0.88, zorder=22))

        if state:
            parts = []
            for lab, d in [('정면', state.d_front_m),
                           ('좌', state.d_left_m),
                           ('우', state.d_right_m)]:
                if d is not None:
                    parts.append(f'{lab} {d:.1f}m')
                else:
                    parts.append(f'{lab} —')
            distance_text = '     ·     '.join(parts)
        else:
            distance_text = ''

        ax.text(
            W / 2, top_h + sub_h / 2, distance_text,
            color='#FFDE59', fontsize=13, weight='bold',
            ha='center', va='center', zorder=23,
        )

        # --- 좌하단 세로 stack (해설 자막) ---
        if state:
            actives = []
            ordered = sorted(
                [w for w in [state.fcw, state.ldw, state.bsw, state.head]
                 if w.level > 0],
                key=lambda w: -w.level)
            for w in ordered:
                c = S['warning_colors'][w.name]
                reason = w.reason or f'L{w.level}'
                actives.append((w.name, w.level, reason, c))

            if actives:
                # 좌하단에서 위로 쌓기 (가장 심각한 것이 맨 위에 보이도록 역순)
                margin_x = 0.02
                margin_y = 0.02
                line_h = 0.040    # H 비율 (pill 한 줄 높이)
                gap = 0.012

                n = len(actives)
                # 맨 아래 pill 의 y 위치
                y_base = H * (1 - margin_y)
                for idx, (name, level, reason, c) in enumerate(reversed(actives)):
                    y_pos = y_base - idx * (H * (line_h + gap))
                    ax.text(
                        W * margin_x, y_pos,
                        f'  [{name}·L{level}]  {reason}  ',
                        color='white',
                        fontsize=S['youtube_bottom_font_size'],
                        weight='bold', ha='left', va='bottom', zorder=24,
                        bbox=dict(boxstyle='round,pad=0.35',
                                  facecolor=c, edgecolor='white',
                                  linewidth=1.2, alpha=0.92),
                    )

        # youtube_mode 에선 기존 distance card / lane fail pill 위치 충돌 가능
        # lane_fail 은 상단 bar 위에 덮어쓰지 않도록 그대로 두고,
        # distance card 는 하단 bar 위에 올라가므로 숨김 (이미 자막에 정보 있음)

    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)
    ax.axis('off')


# ============================================================
# Gallery — 10장 일괄 렌더 (도메인 테스트 용)
# ============================================================
def render_gallery(image_paths, results, save_path=None,
                   ncols=2, title=None, style=None, dpi=110,
                   fig_width_per_col=9.0):
    """여러 장 HUD 를 grid 로 렌더.

    Args:
        image_paths:  이미지 경로 리스트 (Path 또는 str)
        results:      {filename: result_dict}  — assessor.assess() 결과
                      (내부 객체 _state 등 포함되어 있어야 함)
        save_path:    None 이면 화면 표시, 경로 주면 파일 저장
        ncols:        grid column 수 (기본 2)
        title:        figure suptitle
        style:        STYLE 오버라이드 partial dict
        fig_width_per_col: 한 열의 너비 (inch, 기본 9)
    """
    paths = [Path(p) for p in image_paths]
    n = len(paths)
    nrows = (n + ncols - 1) // ncols

    # 첫 이미지로 aspect 추정
    first_img = np.array(Image.open(paths[0]).convert('RGB'))
    H0, W0 = first_img.shape[:2]
    aspect = H0 / W0

    fig, axes = plt.subplots(
        nrows, ncols,
        figsize=(fig_width_per_col * ncols,
                 fig_width_per_col * aspect * nrows),
        dpi=dpi,
    )
    axes = np.atleast_2d(axes).flatten()

    for i, path in enumerate(paths):
        ax = axes[i]
        img = np.array(Image.open(path).convert('RGB'))
        res = results.get(path.name)
        if res is None:
            ax.imshow(img)
            ax.set_title(f'{path.name}\n(result 없음)', fontsize=9, color='red')
            ax.axis('off')
            continue
        draw_hud_v5_clean(ax, img, res, style=style)
        # 하단 caption — GT / pred 간단 표시
        gt = res.get('gt')
        pred = res.get('bin')
        cap = path.name.replace('화면 캡처 2026-04-23 ', 'Frame ').replace('.png', '')
        if gt and pred:
            mark = '✓' if gt == pred else '✗'
            cap = f'{cap}   GT:{gt} / pred:{pred} {mark}'
        ax.set_title(cap, fontsize=10, pad=6)

    # 빈 subplot 숨기기
    for j in range(n, len(axes)):
        axes[j].axis('off')

    if title:
        fig.suptitle(title, fontsize=14, weight='bold', y=0.995)

    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=dpi, bbox_inches='tight', pad_inches=0.2,
                    facecolor='white')
        print(f'[clean-HUD] 저장: {save_path}')
        plt.close(fig)
        return save_path
    return fig


# ============================================================
# 간이 self-test (단독 import 확인용)
# ============================================================
if __name__ == '__main__':
    print('hud_v5_clean.py — OK. 사용법은 docstring 참고.')
    print('STYLE keys:', list(STYLE.keys()))
