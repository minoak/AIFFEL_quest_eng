# -*- coding: utf-8 -*-
"""시각화 헬퍼 모음 (presentation layer).

이 모듈은 순수 렌더링만 담당한다. 외부 네트워크/OpenAI 호출 금지.
- matplotlib: 한글 폰트 설정 + 네트워크 그래프 폴백.
- plotly: 게이지(go.Indicator).
- streamlit: 점수 막대/반응 카드/말풍선 (함수 안에서만 st 호출).
- pyvis: 전파 네트워크 그래프 HTML 생성 (실패 시 빈 문자열 반환).

주의:
- 최상단에서 st.set_page_config 등 부수효과 실행 금지. 모든 st 호출은 함수 안에서만.
- pyvis 는 설치 안 돼 있을 수 있으므로 함수 내부에서 lazy import 한다.
"""

import matplotlib.pyplot as plt
import plotly.graph_objects as go
import streamlit as st
import networkx as nx


# ─────────────────────────────────────────────────────────────────────────
# 전역 스타일 사전 (팀 공용 색/라벨 약속)
# ─────────────────────────────────────────────────────────────────────────
STYLE = {
    # 입장(stance)별 색 — 찬성/반대/혼합
    "stance_colors": {
        "support": "#27AE60",   # 찬성 = 초록
        "oppose": "#E74C3C",    # 반대 = 빨강
        "mixed": "#F39C12",     # 혼합 = 주황
    },
    # 노드 상태(node_status)별 색 — 전파 그래프 노드 색칠용
    "node_status_colors": {
        "정상": "#27AE60",      # 정상 = 초록
        "고립": "#9E9E9E",      # 고립(연결 없음) = 회색
        "오해": "#E74C3C",      # 오해(잘못 이해) = 빨강
        "포기": "#8E44AD",      # 포기(신청 안 함) = 보라
        "미도달": "#cfcfcf",    # 미도달(정보 못 받음) = 연회색
    },
    # 게이지 구간 색 — 낮음/중간/높음
    "gauge_bands": {
        "low": "#27AE60",       # 낮음 = 초록
        "mid": "#F1C40F",       # 중간 = 노랑
        "high": "#E74C3C",      # 높음 = 빨강
    },
    # 5축 점수 한글 라벨 (Scores 키 → 표시 이름)
    "score_labels": {
        "understanding": "이해도",
        "benefit": "수혜가능성",
        "intent": "신청의향",
        "dissatisfaction": "불만도",
        "shareability": "공유가능성",
    },
    # chip 기본 색
    "chip_bg": "#ECF0F1",
    "chip_fg": "#2C3E50",
    # 채팅 자기 말풍선 색 (카카오 노랑)
    "chat_self_bubble": "#FEE500",
    # 네트워크 렌더링 엔진 식별자
    "network_engine": "pyvis",
}

# stance 한글 표기 (헤더용)
_STANCE_LABEL = {
    "support": "찬성",
    "oppose": "반대",
    "mixed": "혼합",
}

# 점수 표시 순서 (Scores 정의 순서와 동일하게 고정)
_SCORE_ORDER = [
    "understanding",
    "benefit",
    "intent",
    "dissatisfaction",
    "shareability",
]


# ─────────────────────────────────────────────────────────────────────────
# 한글 폰트
# ─────────────────────────────────────────────────────────────────────────
def set_korean_font():
    """matplotlib 한글 폰트를 설정한다.

    OS별로 사용 가능한 폰트를 우선순위 리스트로 넘겨 깨짐을 방지하고,
    음수 부호(−)가 □ 로 나오는 문제도 막는다.
    """
    plt.rcParams["font.family"] = [
        "Malgun Gothic",   # Windows
        "AppleGothic",     # macOS
        "NanumGothic",     # Linux(나눔)
        "DejaVu Sans",     # 최종 폴백
    ]
    plt.rcParams["axes.unicode_minus"] = False


# ─────────────────────────────────────────────────────────────────────────
# chip (둥근 HTML 배지)
# ─────────────────────────────────────────────────────────────────────────
def chip(text, bg=None, fg=None):
    """둥근 모서리의 작은 HTML 배지(span) 문자열을 반환한다.

    st.markdown(..., unsafe_allow_html=True) 로 출력하는 용도.
    bg/fg 미지정 시 STYLE 기본색 사용.
    """
    bg = bg or STYLE["chip_bg"]
    fg = fg or STYLE["chip_fg"]
    # 안전을 위해 문자열화 + 최소한의 꺾쇠 이스케이프
    safe = str(text).replace("<", "&lt;").replace(">", "&gt;")
    return (
        "<span style=\""
        f"display:inline-block;background:{bg};color:{fg};"
        "padding:2px 10px;margin:2px 3px;border-radius:12px;"
        "font-size:0.78rem;line-height:1.4;white-space:nowrap;"
        "\">"
        f"{safe}</span>"
    )


# ─────────────────────────────────────────────────────────────────────────
# gauge (plotly Indicator)
# ─────────────────────────────────────────────────────────────────────────
def gauge(value, label, bands=None):
    """0~100 범위의 반원형 게이지 Figure 를 만든다.

    value : 표시할 값 (0~100 로 클램프).
    label : 게이지 상단 한글 라벨.
    bands : {'low','mid','high'} 색 사전 (미지정 시 STYLE 사용).
    """
    bands = bands or STYLE["gauge_bands"]

    # 값 보정 — 숫자 아님/None/범위 밖 방어
    try:
        v = float(value)
    except (TypeError, ValueError):
        v = 0.0
    v = max(0.0, min(100.0, v))

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=v,
            title={"text": label, "font": {"size": 16}},
            number={"font": {"size": 28}, "suffix": ""},
            gauge={
                "axis": {
                    "range": [0, 100],
                    "tickwidth": 1,
                    "tickcolor": "#7f8c8d",
                },
                "bar": {"color": "#34495E"},  # 현재 값 바늘 바
                "borderwidth": 0,
                # 3구간 색칠: 낮음(0~33)/중간(33~66)/높음(66~100)
                "steps": [
                    {"range": [0, 33], "color": bands["low"]},
                    {"range": [33, 66], "color": bands["mid"]},
                    {"range": [66, 100], "color": bands["high"]},
                ],
                "threshold": {
                    "line": {"color": "#2C3E50", "width": 3},
                    "thickness": 0.75,
                    "value": v,
                },
            },
        )
    )
    # 컴팩트한 여백
    fig.update_layout(
        height=220,
        margin=dict(l=20, r=20, t=50, b=10),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# ─────────────────────────────────────────────────────────────────────────
# score_bars (streamlit progress 5축)
# ─────────────────────────────────────────────────────────────────────────
def score_bars(scores: dict):
    """5축 점수를 st.progress 막대 5개로 표시한다.

    scores : Scores 형태 dict (0~100 정수값).
    각 막대 텍스트 = '라벨 값'. st 호출 함수이므로 반환값 없음.
    """
    scores = scores or {}
    for key in _SCORE_ORDER:
        label = STYLE["score_labels"].get(key, key)
        # 값 보정 — None/문자/범위 밖 방어
        raw = scores.get(key, 0)
        try:
            v = int(round(float(raw)))
        except (TypeError, ValueError):
            v = 0
        v = max(0, min(100, v))
        # st.progress 는 0.0~1.0 비율을 받는다
        st.progress(v / 100.0, text=f"{label} {v}")


# ─────────────────────────────────────────────────────────────────────────
# render_reaction_card (시민 반응 카드)
# ─────────────────────────────────────────────────────────────────────────
def render_reaction_card(reaction, persona, style=None):
    """페르소나 1명의 반응을 카드 형태로 렌더링한다.

    구성:
      1) 이름 + 데모그래픽 chip 들
      2) stance(찬성/반대/혼합) 색 헤더
      3) 5축 점수 막대(score_bars)
      4) 반응 텍스트
      5) 근거(evidence) expander
    st 호출 함수이므로 반환값 없음.
    """
    style = style or STYLE
    reaction = reaction or {}
    persona = persona or {}

    stance = reaction.get("stance", "mixed")
    stance_color = style["stance_colors"].get(stance, style["stance_colors"]["mixed"])
    stance_kr = _STANCE_LABEL.get(stance, "혼합")

    with st.container(border=True):
        # ── 1) 이름 + 데모그래픽 chip ──────────────────────────
        name = persona.get("name") or "(이름 미상)"
        desc = persona.get("description") or ""
        st.markdown(f"**{name}**" + (f" · {desc}" if desc else ""))

        demo = persona.get("demographics") or {}
        # 표시할 데모그래픽 키 순서/라벨 (값이 있을 때만 chip)
        demo_fields = [
            ("sex", ""),
            ("age", "세"),
            ("marital_status", ""),
            ("housing_type", ""),
            ("occupation", ""),
            ("district", ""),
            ("province", ""),
        ]
        chips = []
        for fkey, suffix in demo_fields:
            val = demo.get(fkey)
            if val in (None, "", []):
                continue
            text = f"{val}{suffix}" if suffix else str(val)
            chips.append(chip(text))
        if chips:
            st.markdown("".join(chips), unsafe_allow_html=True)

        # ── 2) stance 색 헤더 ──────────────────────────────────
        st.markdown(
            "<div style=\""
            f"background:{stance_color};color:#ffffff;"
            "padding:4px 12px;border-radius:8px;margin:6px 0;"
            "font-weight:600;display:inline-block;\">"
            f"{stance_kr}</div>",
            unsafe_allow_html=True,
        )

        # grounded 가 False(ablation) 면 표식 — 일반 시민 응답임을 알림
        if reaction.get("grounded") is False:
            st.caption("페르소나 미적용(일반 시민) 응답")

        # ── 3) 5축 점수 막대 ───────────────────────────────────
        score_bars(reaction.get("scores", {}))

        # ── 4) 반응 텍스트 ─────────────────────────────────────
        text = reaction.get("text") or ""
        if text:
            st.markdown(text)

        # 예상 행동(actions) 이 있으면 chip 으로 한 줄 표시
        actions = reaction.get("actions") or []
        if actions:
            act_chips = "".join(
                chip(str(a), bg="#EAF2F8", fg="#21618C") for a in actions
            )
            st.markdown(act_chips, unsafe_allow_html=True)

        # ── 5) 근거 expander ───────────────────────────────────
        evidence = reaction.get("evidence") or []
        if evidence:
            with st.expander(f"근거 보기 ({len(evidence)}건)"):
                for i, ev in enumerate(evidence, 1):
                    st.markdown(f"{i}. {ev}")


# ─────────────────────────────────────────────────────────────────────────
# 전파 네트워크 그래프: 공용 노드/엣지 추출
# ─────────────────────────────────────────────────────────────────────────
def _persona_label(persona):
    """노드 라벨용 짧은 표기 — 이름 우선, 없으면 description/ id."""
    return (
        persona.get("name")
        or persona.get("description")
        or str(persona.get("id", ""))
    )


def _build_edges(interactions):
    """interactions(또는 edges 호환) 리스트에서 (from_id, to_id) 엣지 목록 추출.

    to_id 가 None(broadcast) 이거나 자기 자신인 엣지는 제외한다.
    """
    edges = []
    for it in interactions or []:
        if not isinstance(it, dict):
            continue
        f = it.get("from_id") or it.get("from")
        t = it.get("to_id") or it.get("to")
        if not f or not t or f == t:
            continue
        edges.append((f, t))
    return edges


# ─────────────────────────────────────────────────────────────────────────
# propagation_graph (pyvis HTML)
# ─────────────────────────────────────────────────────────────────────────
def propagation_graph(interactions, personas, node_status, style=None):
    """pyvis 로 전파 네트워크 그래프 HTML 문자열을 만든다.

    노드 = 페르소나(node_status 에 따라 색칠).
    엣지 = interactions 의 from→to 전파.
    pyvis 미설치/실패 시 빈 문자열('') 반환 → 호출부에서 폴백 사용.
    """
    style = style or STYLE
    node_status = node_status or {}

    # pyvis 는 환경에 따라 없을 수 있으므로 함수 내부에서 lazy import
    try:
        from pyvis.network import Network
    except Exception:
        return ""

    try:
        net = Network(
            height="520px",
            width="100%",
            bgcolor="#ffffff",
            font_color="#2C3E50",
            directed=True,
            notebook=False,
        )
        # 물리 엔진 — 적당히 퍼지게
        net.barnes_hut(
            gravity=-8000,
            central_gravity=0.3,
            spring_length=120,
            spring_strength=0.04,
        )

        status_colors = style["node_status_colors"]
        default_color = status_colors.get("정상", "#27AE60")

        # ── 노드 추가 ─────────────────────────────────────────
        for p in personas or []:
            pid = p.get("id")
            if not pid:
                continue
            status = node_status.get(pid, "정상")
            color = status_colors.get(status, default_color)
            label = _persona_label(p)
            title = f"{label} · 상태: {status}"  # 마우스오버 툴팁
            net.add_node(
                pid,
                label=label,
                title=title,
                color=color,
                shape="dot",
                size=18,
            )

        # ── 엣지 추가 (양끝 노드가 모두 존재할 때만) ───────────
        node_ids = {p.get("id") for p in (personas or []) if p.get("id")}
        for f, t in _build_edges(interactions):
            if f in node_ids and t in node_ids:
                net.add_edge(f, t, color="#B2BABB", arrows="to")

        # generate_html 은 파일 저장 없이 HTML 문자열만 반환
        return net.generate_html(notebook=False)
    except Exception:
        # pyvis 내부 오류 시에도 앱이 죽지 않도록 폴백 신호
        return ""


# ─────────────────────────────────────────────────────────────────────────
# propagation_graph_mpl (networkx 폴백)
# ─────────────────────────────────────────────────────────────────────────
def propagation_graph_mpl(interactions, personas, node_status, style=None):
    """networkx + matplotlib 로 전파 그래프 Figure 를 만든다 (pyvis 폴백).

    spring_layout 으로 배치하고 node_status 색으로 노드를 칠한다.
    한글 라벨이 깨지지 않도록 set_korean_font() 를 먼저 호출한다.
    """
    style = style or STYLE
    node_status = node_status or {}
    set_korean_font()  # 한글 폰트 보장

    status_colors = style["node_status_colors"]
    default_color = status_colors.get("정상", "#27AE60")

    # 그래프 구성
    g = nx.DiGraph()
    labels = {}
    colors = []

    for p in personas or []:
        pid = p.get("id")
        if not pid:
            continue
        g.add_node(pid)
        labels[pid] = _persona_label(p)

    node_ids = set(g.nodes())
    for f, t in _build_edges(interactions):
        if f in node_ids and t in node_ids:
            g.add_edge(f, t)

    # 노드 순서대로 색 매핑 (그려지는 노드 순서와 일치시킴)
    for pid in g.nodes():
        status = node_status.get(pid, "정상")
        colors.append(status_colors.get(status, default_color))

    fig, ax = plt.subplots(figsize=(7, 5))

    # 노드가 없으면 빈 안내 Figure 반환
    if g.number_of_nodes() == 0:
        ax.text(0.5, 0.5, "전파 데이터가 없습니다.",
                ha="center", va="center", fontsize=12)
        ax.axis("off")
        fig.tight_layout()
        return fig

    # 재현 가능한 배치
    pos = nx.spring_layout(g, seed=42, k=0.8)

    nx.draw_networkx_nodes(
        g, pos, ax=ax, node_color=colors, node_size=600, alpha=0.95,
        edgecolors="#ffffff", linewidths=1.5,
    )
    if g.number_of_edges() > 0:
        nx.draw_networkx_edges(
            g, pos, ax=ax, edge_color="#B2BABB", arrows=True,
            arrowstyle="-|>", arrowsize=12, width=1.2,
            connectionstyle="arc3,rad=0.05",
        )
    nx.draw_networkx_labels(
        g, pos, labels=labels, ax=ax, font_size=8,
        font_family=plt.rcParams["font.family"][0],
    )

    ax.set_title("정보 전파 네트워크", fontsize=13)
    ax.axis("off")
    fig.tight_layout()
    return fig


# ─────────────────────────────────────────────────────────────────────────
# chat_bubble (st.chat_message 말풍선)
# ─────────────────────────────────────────────────────────────────────────
def chat_bubble(message, is_self=False):
    """채팅 말풍선 1개를 그린다.

    is_self=True 면 카카오 노란색 배경의 '나' 말풍선,
    아니면 기본 '상대' 말풍선. st 호출 함수이므로 반환값 없음.
    message 는 문자열 또는 {'name':..,'text':..} dict 모두 허용.
    """
    # message 정규화
    name = None
    if isinstance(message, dict):
        name = message.get("name") or message.get("from")
        text = message.get("text") or message.get("content") or ""
    else:
        text = str(message)

    if is_self:
        # 자신 = 노란 말풍선 (오른쪽 정렬 느낌의 배경 박스)
        with st.chat_message("user"):
            if name:
                st.caption(name)
            st.markdown(
                "<div style=\""
                f"background:{STYLE['chat_self_bubble']};color:#2C3E50;"
                "padding:8px 12px;border-radius:14px;display:inline-block;"
                "max-width:90%;\">"
                f"{str(text)}</div>",
                unsafe_allow_html=True,
            )
    else:
        # 상대 = 기본 말풍선
        with st.chat_message("assistant"):
            if name:
                st.caption(name)
            st.markdown(str(text))
