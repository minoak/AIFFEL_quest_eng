"""미리랩 - 정책 반응 시뮬레이터 (오케스트레이터/엔트리포인트).

이 파일은 Streamlit 앱의 최상위 진입점이다.
- 한글 폰트 설정 후 페이지 설정/타이틀을 그린다.
- 사이드바에서 정책 선택·시민 수·데모 모드를 받고, 버튼 클릭 시 시뮬레이션을 실행한다.
- 실행 결과(SimState)와 그 뷰모델(ViewModel)을 session_state 에 저장한다.
- 본문은 7개 탭으로 구성되며, 각 탭은 해당 render_*_tab(view) 를 호출한다.

주의: import 시점에는 네트워크/OpenAI 호출이 절대 일어나지 않는다.
실제 호출은 '시뮬레이션 실행' 버튼을 눌렀을 때만 run_simulation 내부에서 발생한다.
"""

# --- 최상단: 한글 폰트 → 페이지 설정 → 타이틀 (이 순서 고정) ---
from viz import set_korean_font

set_korean_font()

import streamlit as st

st.set_page_config(page_title="미리랩 - 정책 반응 시뮬레이터", layout="wide")
st.title("미리랩 — 정책 반응 시뮬레이터")

# --- 나머지 import (계약상 정해진 공개 API만 사용) ---
from sample_policies import SAMPLES, DEFAULT_POLICY
from ui.state_helpers import run_simulation
from ui.model import build_view
from graph.llm import has_real_key
from ui import (
    tab_input,
    tab_dashboard,
    tab_chat,
    tab_network,
    tab_improve,
    tab_abtest,
    tab_board,
)


# =====================================================================
# 사이드바: 입력 컨트롤 + 실행 트리거
# =====================================================================
def _render_sidebar() -> None:
    """사이드바를 그리고, '실행' 버튼이 눌리면 시뮬레이션을 수행한다.

    - 정책 선택 selectbox: 샘플 정책명 + '직접 입력'.
    - text_area: 선택한 샘플 원문을 프리필(직접 입력이면 빈칸).
    - 시민 수 number_input(8~30, 기본 24).
    - 데모 모드 checkbox(키 없으면 기본 체크).
    - 실행 버튼 클릭 시 run_simulation → build_view 결과를 session_state 저장.
    """
    with st.sidebar:
        st.header("시뮬레이션 설정")

        # 1) 정책 선택 ---------------------------------------------------
        policy_names = list(SAMPLES)
        options = policy_names + ["직접 입력"]
        # 기본 선택: DEFAULT_POLICY 가 샘플 목록에 있으면 그것을, 없으면 첫 항목.
        try:
            default_index = options.index(DEFAULT_POLICY)
        except ValueError:
            default_index = 0
        choice = st.selectbox("정책 선택", options, index=default_index)

        # 2) 선택에 따른 원문 프리필 ------------------------------------
        if choice == "직접 입력":
            prefill = ""
        else:
            prefill = SAMPLES.get(choice, "")

        # selectbox 선택이 바뀌면 text_area 가 새 원문으로 갱신되도록
        # key 에 선택값을 포함시킨다(선택 변경 = 위젯 재생성 → 프리필 반영).
        policy_text = st.text_area(
            "정책 원문",
            value=prefill,
            height=260,
            key=f"policy_text::{choice}",
            help="샘플을 고르면 원문이 채워집니다. '직접 입력'을 고르면 직접 작성하세요.",
        )

        # 3) 시민 수 -----------------------------------------------------
        n = st.number_input(
            "시민 수",
            min_value=8,
            max_value=30,
            value=24,
            step=1,
            help="시뮬레이션에 참여할 가상 시민(페르소나) 수입니다.",
        )

        # 4) 데모 모드 ---------------------------------------------------
        real_key = has_real_key()
        demo = st.checkbox(
            "데모 모드(키 없이 모의 데이터)",
            value=not real_key,
            help="체크하면 OpenAI 호출 없이 모의 데이터로 화면을 채웁니다.",
        )
        if not real_key:
            st.caption(
                "OpenAI 키가 설정되지 않아 데모 모드를 권장합니다. "
                "실제 LLM 반응을 보려면 .env 에 OPENAI_API_KEY 를 설정하세요."
            )

        # 5) 실행 버튼 ---------------------------------------------------
        run_clicked = st.button(
            "시뮬레이션 실행", type="primary", use_container_width=True
        )

    # --- 버튼 클릭 처리(사이드바 컨텍스트 밖에서 스피너 표시) ---------
    if run_clicked:
        policy = (policy_text or "").strip()
        if not policy:
            st.warning("정책 원문이 비어 있습니다. 샘플을 선택하거나 직접 입력해 주세요.")
            return

        spinner_msg = (
            "모의 데이터를 생성하는 중입니다..."
            if demo
            else "가상 시민들이 정책을 읽고 반응하는 중입니다..."
        )
        with st.spinner(spinner_msg):
            try:
                sim = run_simulation(policy, mock=demo, n=int(n))
                st.session_state["sim"] = sim
                st.session_state["view"] = build_view(sim)
            except Exception as e:  # 실행 실패 시 화면을 깨뜨리지 않고 예외 표시.
                st.session_state["sim"] = None
                st.session_state["view"] = None
                st.error("시뮬레이션 실행 중 오류가 발생했습니다.")
                st.exception(e)
                return

        if demo:
            st.success("모의 데이터로 시뮬레이션을 완료했습니다. 아래 탭에서 확인하세요.")
        else:
            st.success("시뮬레이션을 완료했습니다. 아래 탭에서 결과를 확인하세요.")


# =====================================================================
# 본문: 7개 탭
# =====================================================================
def _render_body() -> None:
    """본문 탭들을 그린다. view 가 없으면 각 탭이 알아서 안내(st.info)한다."""
    tab_labels = [
        "정책 입력",
        "시민 반응",
        "SNS 채팅방",
        "전파 그래프",
        "개선 제안",
        "AB 테스트",
        "게시판",
    ]
    tabs = st.tabs(tab_labels)
    view = st.session_state.get("view")

    # 각 탭과 렌더 함수를 1:1로 매핑한다(라벨 순서와 동일).
    renderers = [
        tab_input.render_input_tab,
        tab_dashboard.render_dashboard_tab,
        tab_chat.render_chat_tab,
        tab_network.render_network_tab,
        tab_improve.render_improve_tab,
        tab_abtest.render_abtest_tab,
        tab_board.render_board_tab,
    ]

    for i, render_fn in enumerate(renderers):
        with tabs[i]:
            try:
                render_fn(view)
            except Exception as e:  # 한 탭이 죽어도 다른 탭은 살아 있도록 격리.
                st.exception(e)


# =====================================================================
# 진입점
# =====================================================================
def main() -> None:
    _render_sidebar()
    _render_body()


main()
