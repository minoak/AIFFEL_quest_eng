"""A/B 테스트 탭 (stretch).

현재 정책의 시뮬 결과(view)와 사용자가 입력한 '수정안' 정책의 시뮬 결과(view_b)를
좌/우로 나란히 놓고, 핵심 지표 3개를 게이지 + delta 로 비교한다.

공개 API: render_abtest_tab(view)
- view: ui.model.build_view(sim) 가 만든 ViewModel(dict). None 이면 안내 후 return.
- 수정안 시뮬은 버튼을 눌렀을 때만 실행되며, 결과는 session_state['view_b'] 에 저장한다.
- mock 토글을 켜면 외부(OpenAI) 호출 없이 ui.mock 기반으로 빠르게 비교 가능.
"""
import streamlit as st

from viz import gauge


# A/B 로 비교할 핵심 지표 정의: (표시 라벨, view/metrics 에서 찾을 후보 키들, 게이지 단위)
# metrics 키 이름이 환경마다 조금씩 다를 수 있어 후보를 여러 개 두고 순서대로 탐색한다.
_METRICS = [
    ("정책수용도", ["acceptance", "정책수용도", "policy_acceptance"]),
    ("신청의향지수", ["intent", "신청의향지수", "apply_intent", "intent_index"]),
    ("사회혼란도", ["unrest", "사회혼란도", "social_unrest"]),
]


def _pick_metrics(view):
    """view(또는 그 안의 metrics)에서 게이지로 그릴 (라벨, 값) 3개를 안전하게 뽑는다."""
    if not isinstance(view, dict):
        return [(label, 0.0) for label, _ in _METRICS]

    # metrics 는 view 바로 아래 또는 view['metrics'] 둘 다 지원한다.
    metrics = view.get("metrics") if isinstance(view.get("metrics"), dict) else view

    picked = []
    for label, keys in _METRICS:
        value = 0.0
        for k in keys:
            if isinstance(metrics, dict) and k in metrics and metrics[k] is not None:
                try:
                    value = float(metrics[k])
                except (TypeError, ValueError):
                    value = 0.0
                break
        picked.append((label, value))
    return picked


def _render_gauges(view, *, compare=None):
    """게이지 3개를 세로로 그린다. compare(상대편 값 dict)가 있으면 st.metric 으로 delta 표시."""
    rows = _pick_metrics(view)
    cmp_map = dict(compare) if compare else {}

    for label, value in rows:
        # 게이지(plotly) 본체
        st.plotly_chart(
            gauge(value, label),
            use_container_width=True,
            key=f"abtest_gauge_{id(view)}_{label}",
        )
        # 비교 대상이 있으면 수치 + 변화량(delta) 을 함께 보여준다.
        if compare is not None and label in cmp_map:
            delta = round(value - cmp_map[label], 1)
            st.metric(label=label, value=round(value, 1), delta=delta)


def render_abtest_tab(view):
    """A/B 테스트 탭 렌더 진입점."""
    # --- None 가드: 아직 시뮬을 안 돌렸으면 안내만 ---
    if view is None:
        st.info("먼저 '시뮬레이션 실행'으로 현재 정책 결과를 만든 뒤, 이 탭에서 수정안과 비교하세요.")
        return

    st.subheader("A/B 테스트 — 현재 정책 vs 수정안")
    st.caption(
        "왼쪽은 현재 시뮬 결과, 오른쪽은 아래에 입력한 '수정안' 정책의 시뮬 결과입니다. "
        "정책 문구를 다듬은 뒤 같은 시민들이 어떻게 반응이 달라지는지 핵심 지표 3개로 비교합니다."
    )

    # --- 수정안 입력 영역 ---
    # 현재 정책 원문을 기본값으로 깔아 두어, 사용자가 일부만 고쳐 비교하기 쉽게 한다.
    base_policy = ""
    if isinstance(view, dict):
        base_policy = view.get("policy") or ""

    policy_b = st.text_area(
        "수정안 정책",
        value=base_policy,
        height=200,
        help="현재 정책을 복사해 둔 상태입니다. 문장을 다듬거나 조건을 바꿔 보세요.",
        key="abtest_policy_b",
    )

    col_run, col_mock = st.columns([3, 2])
    with col_mock:
        # 데모/오프라인 시 외부 호출 없이 빠르게 비교하기 위한 토글
        use_mock = st.checkbox(
            "목업으로 빠르게(외부 호출 없음)",
            value=False,
            key="abtest_use_mock",
        )
    with col_run:
        run_clicked = st.button(
            "수정안 시뮬 실행",
            type="primary",
            use_container_width=True,
            key="abtest_run_btn",
        )

    # --- 버튼: 수정안 시뮬 실행 ---
    if run_clicked:
        if not policy_b.strip():
            st.warning("수정안 정책 내용을 입력하세요.")
        else:
            # import 는 함수 안에서(임포트 시점 네트워크/무거운 의존 회피)
            from ui.state_helpers import run_simulation
            from ui.model import build_view

            with st.spinner("수정안으로 시뮬레이션 중..."):
                try:
                    sim_b = run_simulation(policy_b, mock=use_mock)
                    st.session_state["view_b"] = build_view(sim_b)
                    st.success("수정안 시뮬이 완료되었습니다. 아래에서 비교하세요.")
                except Exception as e:  # 데모 안정성: 실패해도 탭이 죽지 않게
                    st.error(f"수정안 시뮬 실행 중 오류: {e}")

    # --- 좌/우 비교 ---
    view_b = st.session_state.get("view_b")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("#### 현재 정책")
        if view_b is not None:
            # 오른쪽(수정안)과 delta 비교: 왼쪽 기준 변화량을 보여줌
            _render_gauges(view, compare=_pick_metrics(view_b))
        else:
            _render_gauges(view)
    with col_b:
        st.markdown("#### 수정안")
        if view_b is None:
            st.info("위에서 수정안 정책을 입력하고 '수정안 시뮬 실행'을 누르면 여기에 결과가 나타납니다.")
        else:
            # 왼쪽(현재)과 delta 비교: 수정안이 현재 대비 얼마나 변했는지
            _render_gauges(view_b, compare=_pick_metrics(view))
