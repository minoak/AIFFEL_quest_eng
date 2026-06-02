"""전파 네트워크 탭.

정책 정보가 시민들 사이에서 어떻게 퍼지는지(혹은 못 퍼지는지)를
네트워크 그래프로 보여준다.

- 노드 = 시민(페르소나), 색 = 전파 상태(도달/고립/오해)
- 엣지 = 전파(공유) 경로
- 우선 pyvis 인터랙티브 그래프(html)를 components.html 로 임베드하고,
  html 이 비었거나 렌더 중 예외가 나면 matplotlib 정적 그래프로 폴백한다.

이 탭은 view(=build_view 결과)만 읽는다. 외부 호출/네트워크는 없다.
view 가 None 이면 안내만 띄우고 return.
"""

import streamlit as st
import streamlit.components.v1 as components

from viz import propagation_graph, propagation_graph_mpl


# --- 전파 상태 표준화 -------------------------------------------------------
# node_status 값이 모듈/버전에 따라 한글/영문/약자로 들어올 수 있어
# 세 가지 표준 상태('reached'/'isolated'/'misunderstood')로 정규화한다.
# 색은 viz 의 노드 색과 의미가 일치하도록 잡았다(초록=도달, 회색=고립, 주황=오해).
_STATUS_DEFS = [
    {
        "key": "reached",
        "label": "도달",
        "color": "#2E7D32",
        "help": "정책 정보가 전달된 시민",
        "aliases": {
            "reached", "도달", "전달", "수신", "informed",
            "ok", "received", "active",
        },
    },
    {
        "key": "isolated",
        "label": "고립",
        "color": "#9E9E9E",
        "help": "정보가 닿지 못한 시민 (정보 미도달)",
        "aliases": {
            "isolated", "고립", "미도달", "isolate", "unreached",
            "disconnected", "none", "off",
        },
    },
    {
        "key": "misunderstood",
        "label": "오해",
        "color": "#EF6C00",
        "help": "정보가 왜곡·오해되어 퍼진 시민",
        "aliases": {
            "misunderstood", "오해", "왜곡", "misinformed",
            "confused", "wrong", "misunderstand",
        },
    },
]

# 빠른 조회용 alias -> 표준 def 매핑
_ALIAS_TO_DEF = {}
for _d in _STATUS_DEFS:
    for _a in _d["aliases"]:
        _ALIAS_TO_DEF[str(_a).strip().lower()] = _d


def _classify(status_value) -> dict | None:
    """node_status 의 개별 값을 표준 상태 def 로 정규화. 모르면 None."""
    if status_value is None:
        return None
    key = str(status_value).strip().lower()
    if not key:
        return None
    if key in _ALIAS_TO_DEF:
        return _ALIAS_TO_DEF[key]
    # 부분 일치(예: 'isolated_node', '도달함') 폴백
    for d in _STATUS_DEFS:
        for a in d["aliases"]:
            a = str(a).strip().lower()
            if a and (a in key or key in a):
                return d
    return None


def _count_statuses(node_status) -> dict:
    """node_status(dict[persona_id]=status) 를 표준 상태별 개수로 집계.

    분류되지 않은 값은 '기타'로 따로 센다.
    반환: {'reached': n, 'isolated': n, 'misunderstood': n, '_other': n}
    """
    counts = {d["key"]: 0 for d in _STATUS_DEFS}
    counts["_other"] = 0
    if not node_status:
        return counts
    # dict 면 값들을, 리스트면 원소들을 상태값으로 본다.
    if isinstance(node_status, dict):
        values = node_status.values()
    else:
        try:
            values = list(node_status)
        except TypeError:
            values = []
    for v in values:
        d = _classify(v)
        if d is None:
            counts["_other"] += 1
        else:
            counts[d["key"]] += 1
    return counts


def _render_legend():
    """노드 색 = 상태 범례를 가로로 표기."""
    cols = st.columns(len(_STATUS_DEFS))
    for col, d in zip(cols, _STATUS_DEFS):
        with col:
            st.markdown(
                f"<span style='display:inline-block;width:12px;height:12px;"
                f"border-radius:50%;background:{d['color']};"
                f"margin-right:6px;vertical-align:middle;'></span>"
                f"<span style='vertical-align:middle;'>"
                f"<b>{d['label']}</b> — {d['help']}</span>",
                unsafe_allow_html=True,
            )


def render_network_tab(view):
    """전파 네트워크 탭 본체.

    view: build_view(sim) 결과(ViewModel dict). None 이면 안내 후 return.
    필요한 키: interactions(list), personas(list), node_status(dict).
    style 은 있으면 그대로 viz 에 넘긴다(없어도 동작).
    """
    if view is None:
        st.info("먼저 좌측에서 정책을 입력하고 시뮬레이션을 실행하세요.")
        return

    st.subheader("전파 네트워크")
    st.caption(
        "정책 정보가 시민들 사이에서 어떻게 퍼지는지를 보여줍니다. "
        "노드 = 시민, 색 = 전파 상태, 화살표 = 공유 경로입니다."
    )

    # ViewModel 에서 필요한 조각 추출 (키 누락에 관대하게)
    interactions = view.get("interactions") or []
    personas = view.get("personas") or []
    node_status = view.get("node_status") or {}
    style = view.get("style")  # 없으면 None → viz 가 기본 스타일 사용

    # --- 상단 요약 metric: 도달 / 고립 / 오해 수 ---
    counts = _count_statuses(node_status)
    m1, m2, m3 = st.columns(3)
    m1.metric("도달", f"{counts['reached']}명", help="정책 정보가 전달된 시민 수")
    m2.metric("고립", f"{counts['isolated']}명", help="정보가 닿지 못한 시민 수")
    m3.metric("오해", f"{counts['misunderstood']}명", help="정보를 오해한 시민 수")
    if counts["_other"]:
        st.caption(f"(분류되지 않은 상태 {counts['_other']}명 포함)")

    st.divider()

    # --- 본문: pyvis html 우선, 실패 시 matplotlib 폴백 ---
    rendered = False
    html = None
    try:
        html = propagation_graph(
            interactions, personas, node_status, style=style
        )
    except Exception as e:  # viz 호출 자체 실패
        html = None
        st.warning(f"인터랙티브 그래프 생성에 실패해 정적 그래프로 대체합니다. ({e})")

    # html 이 정상(비어있지 않은 문자열)이면 임베드
    if isinstance(html, str) and html.strip():
        try:
            components.html(html, height=600, scrolling=True)
            rendered = True
        except Exception as e:
            st.warning(f"그래프 임베드에 실패해 정적 그래프로 대체합니다. ({e})")
            rendered = False

    # 폴백: matplotlib 정적 그래프
    if not rendered:
        try:
            fig = propagation_graph_mpl(
                interactions, personas, node_status, style=style
            )
            if fig is not None:
                st.pyplot(fig)
                rendered = True
        except Exception as e:
            st.error(f"네트워크 그래프를 그릴 수 없습니다: {e}")

    if not rendered:
        st.info("아직 전파(공유) 데이터가 없어 그래프를 표시할 수 없습니다.")

    # --- 범례 (노드 색 = 상태) ---
    st.divider()
    st.markdown("**범례 — 노드 색 = 전파 상태**")
    _render_legend()
