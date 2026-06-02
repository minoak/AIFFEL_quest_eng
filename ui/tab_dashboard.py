# -*- coding: utf-8 -*-
"""대시보드 탭: 핵심 지표 게이지 3종 + 시민 반응 카드 그리드를 렌더링한다."""

import streamlit as st

from viz import gauge, render_reaction_card


def render_dashboard_tab(view):
    """ViewModel(view)을 받아 대시보드를 그린다.

    상단: 사회혼란도 / 정책수용도 / 신청의향지수 게이지 3종.
    하단: 페르소나별 시민 반응 카드를 3열 그리드로 표시.
    view가 None이면 안내 후 종료한다.
    """
    # view 없을 때 가드 — 아직 시뮬레이션을 돌리지 않은 상태
    if view is None:
        st.info("아직 시뮬레이션 결과가 없습니다. 정책을 입력하고 시뮬레이션을 실행해 주세요.")
        return

    # ── 상단: 핵심 지표 게이지 3종 ───────────────────────────────
    metrics = view.get("metrics", {}) or {}

    st.subheader("핵심 지표")
    col1, col2, col3 = st.columns(3)

    with col1:
        # 사회혼란도: 갈등/불만 정도 (높을수록 위험)
        fig = gauge(metrics.get("사회혼란도", 0), "사회혼란도")
        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # 정책수용도: 시민이 정책을 받아들이는 정도
        fig = gauge(metrics.get("정책수용도", 0), "정책수용도")
        st.plotly_chart(fig, use_container_width=True)

    with col3:
        # 신청의향지수: 실제 신청/참여로 이어질 의향
        fig = gauge(metrics.get("신청의향지수", 0), "신청의향지수")
        st.plotly_chart(fig, use_container_width=True)

    st.divider()

    # ── 하단: 시민 반응 카드 그리드 ──────────────────────────────
    st.subheader("시민 반응")

    personas = view.get("personas", []) or []
    reactions_by_id = view.get("reactions_by_id", {}) or {}

    if not personas:
        st.info("표시할 페르소나가 없습니다.")
        return

    # 3열 그리드로 순회하며 각 페르소나의 반응 카드를 렌더링
    cols = st.columns(3)
    slot = 0
    for persona in personas:
        # 페르소나 식별자로 해당 반응을 조회
        pid = persona.get("id")
        reaction = reactions_by_id.get(pid)

        # 반응이 없으면 카드를 건너뜀
        if not reaction:
            continue

        with cols[slot % 3]:
            render_reaction_card(reaction, persona)
        slot += 1

    # 페르소나는 있으나 매칭되는 반응이 하나도 없는 경우 안내
    if slot == 0:
        st.info("아직 생성된 시민 반응이 없습니다.")
