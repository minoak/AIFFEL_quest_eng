"""Streamlit 세션/리소스 헬퍼.

UI 계층(app.py, tab_*.py)이 직접 LangGraph·페르소나 로더를 다루지 않도록
캐싱과 폴백을 한곳에 모은다.

공개 API:
- get_graph()                : 컴파일된 그래프(앱) — @st.cache_resource
- get_personas(n, seed)      : 페르소나 리스트 — @st.cache_resource
- run_simulation(...)        : 정책에 대한 시뮬레이션 실행 → 완전한 SimState dict

설계 원칙:
- 임포트 시점에 네트워크/OpenAI 호출 금지(키 없어도 import 되어야 함).
- 키가 없거나 mock 요청이면 외부 호출 없이 sample_simstate 로 데모 동작.
- 실제 실행 중 네트워크/페르소나 로드 실패 시 안내 후 mock 으로 폴백.
"""

import streamlit as st

from graph.build import build_graph
from graph.llm import has_real_key
from ui.mock import sample_simstate
from data.personas import load_personas


@st.cache_resource(show_spinner=False)
def get_graph():
    """컴파일된 LangGraph 앱을 세션 전역에서 1회만 빌드해 재사용한다."""
    return build_graph()


@st.cache_resource(show_spinner=False)
def get_personas(n: int = 24, seed: int = 42):
    """페르소나 리스트를 캐시한다.

    첫 호출에서만 HF 데이터셋 다운로드/샘플링이 일어나고,
    이후 동일 (n, seed) 조합은 캐시된 결과를 즉시 반환한다.
    """
    return load_personas(n, seed)


def run_simulation(
    policy: str,
    mock: bool = False,
    n: int = 24,
    seed: int = 42,
    grounded: bool = True,
    rounds: int = 1,
) -> dict:
    """정책 텍스트에 대한 시뮬레이션을 실행하고 완전한 SimState dict 를 반환한다.

    동작 분기:
    1) mock=True 또는 OpenAI 키 없음  → 외부 호출 없이 sample_simstate 로 데모.
    2) 그 외                         → 페르소나 로드 + 그래프 invoke 로 실제 실행.
       - 페르소나 로드/네트워크/그래프 실행 중 예외 발생 시 경고 후 mock 폴백.

    반환: SimState 형태의 dict (state.SimState 계약 준수).
    """
    # 1) 데모 모드: 명시적 mock 이거나 실제 키가 없으면 즉시 가짜 상태 반환.
    if mock or not has_real_key():
        if mock:
            # 사용자가 의도적으로 데모를 선택한 경우 가볍게 안내.
            st.caption("데모 모드: 샘플 데이터로 결과를 표시합니다(OpenAI 호출 없음).")
        else:
            # 키가 없어 데모로 떨어진 경우만 별도 안내.
            st.info(
                "OpenAI API 키가 없어 데모(샘플) 모드로 실행합니다. "
                "실제 시뮬레이션은 .env 에 OPENAI_API_KEY 를 설정하세요."
            )
        return sample_simstate(policy)

    # 2) 실제 실행 모드: 페르소나 로드 → 그래프 빌드 → invoke.
    try:
        with st.status("시뮬레이션 준비 중...", expanded=False) as status:
            # 2-1) 페르소나 로드(첫 호출 시 다운로드/샘플, 이후 캐시).
            status.update(label="페르소나 불러오는 중...")
            personas = get_personas(n, seed)

            # 2-2) 컴파일된 그래프 확보.
            status.update(label="시뮬레이션 그래프 준비 중...")
            app = get_graph()

            # 2-3) 초기 SimState 구성 후 그래프 실행.
            #      reactions/interactions/edges 는 add 리듀서가 누적하므로 빈 리스트로 시작.
            status.update(label=f"{len(personas)}명 페르소나 반응 생성 중...")
            initial_state = {
                "policy": policy,
                "personas": personas,
                "reactions": [],
                "interactions": [],
                "summary": "",
                "grounded": grounded,
                "rounds": rounds,
                "edges": [],
                "metrics": {},
                "improvements": {},
            }
            result = app.invoke(initial_state)

            status.update(label="시뮬레이션 완료", state="complete")
        return result

    except Exception as exc:  # noqa: BLE001 - 데모 안정성 위해 광범위 폴백.
        # 네트워크/페르소나 로드/그래프 실행 실패 시 데모로 폴백해 UI 가 죽지 않게 한다.
        st.warning(
            f"실제 시뮬레이션 실행에 실패하여 데모(샘플) 결과로 대체합니다. (원인: {exc})"
        )
        return sample_simstate(policy)
