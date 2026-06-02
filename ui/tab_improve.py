# -*- coding: utf-8 -*-
"""개선안 탭.

집계 요약(summary)과 정책 개선 제안(policy_fixes),
그리고 '쉬운 글 변환'(원문 vs 쉬운 글) 비교를 보여준다.
view 는 ui/model.py 의 build_view(sim) 결과(ViewModel) 이다.
"""

import streamlit as st


def render_improve_tab(view):
    """개선안 탭을 렌더링한다.

    매개변수
    --------
    view : dict | None
        ViewModel. 아직 시뮬레이션을 돌리지 않았으면 None 일 수 있다.
        다음 키를 사용한다.
          - 'summary'      : 집계 요약 문장(마크다운)
          - 'policy'       : 원문 정책 텍스트
          - 'improvements' : {'policy_fixes': list[str], 'easy_text': str}
    """
    # view 가 없으면 안내만 하고 종료(시뮬레이션 미실행 상태)
    if view is None:
        st.info("먼저 정책을 입력하고 시뮬레이션을 실행해 주세요. 결과가 나오면 개선안이 여기에 표시됩니다.")
        return

    # ── 1) 집계 요약 ───────────────────────────────────────────────
    st.subheader("집계 요약")
    summary = view.get("summary") or "요약 정보가 아직 없습니다."
    st.markdown(summary)

    st.divider()

    # improvements 안전 추출(키가 비어 있어도 동작하도록)
    improvements = view.get("improvements") or {}
    policy_fixes = improvements.get("policy_fixes") or []
    easy_text = improvements.get("easy_text") or ""

    # ── 2) 정책 개선 제안(번호 목록) ───────────────────────────────
    st.subheader("정책 개선 제안")
    if policy_fixes:
        # 번호를 매겨 한 줄씩 마크다운 정렬 목록으로 출력
        lines = []
        for i, fix in enumerate(policy_fixes, start=1):
            text = str(fix).strip()
            if text:
                lines.append(f"{i}. {text}")
        if lines:
            st.markdown("\n".join(lines))
        else:
            st.caption("제안된 개선안이 없습니다.")
    else:
        st.caption("제안된 개선안이 없습니다.")

    st.divider()

    # ── 3) 쉬운 글 변환(원문 vs 쉬운 글 나란히) ────────────────────
    st.subheader("쉬운 글 변환")
    st.caption("왼쪽은 원문, 오른쪽은 시민이 이해하기 쉽게 다시 쓴 글입니다.")

    policy_text = view.get("policy") or "원문 정책 텍스트가 없습니다."

    col_orig, col_easy = st.columns(2)
    with col_orig:
        st.markdown("**원문 정책**")
        # 원문은 그대로 보여주기 위해 코드/텍스트 영역으로 표시
        st.text_area(
            "원문",
            value=policy_text,
            height=320,
            disabled=True,
            label_visibility="collapsed",
        )
    with col_easy:
        st.markdown("**쉬운 글**")
        if easy_text:
            st.text_area(
                "쉬운 글",
                value=easy_text,
                height=320,
                disabled=True,
                label_visibility="collapsed",
            )
        else:
            st.info("쉬운 글 변환 결과가 아직 없습니다.")

    # 쉬운 글 내려받기(있을 때만 활성화)
    st.download_button(
        label="쉬운 글 내려받기 (.txt)",
        data=(easy_text or "").encode("utf-8"),
        file_name="쉬운글.txt",
        mime="text/plain",
        disabled=(not easy_text),
        use_container_width=True,
    )
