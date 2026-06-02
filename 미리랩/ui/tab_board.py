# -*- coding: utf-8 -*-
"""정책 문의 게시판 탭(stretch).

시민이 정책에 대해 질문을 남기면, 정책 원문을 바탕으로 한 간단한 규칙 기반
자동답변과 가상 시민 댓글 1~2개가 함께 달린다. RAG는 MVP에서 연결하지 않으므로
실제 검색이 아니라 정책 텍스트에서 키워드를 골라 안내 문구를 조립하는 mock 수준이다.

질문/답변 스레드는 session_state['board']에 누적되어 탭을 다시 그려도 유지된다.
"""

import random
import re

import streamlit as st


# ── 규칙 기반 자동답변에 쓰는 키워드 사전 ────────────────────────────
# 질문에 아래 키워드가 들어가면, 정책 원문에서 관련 문장을 우선적으로 끌어와 답한다.
_TOPIC_KEYWORDS = {
    "대상": ["대상", "자격", "누가", "조건", "해당", "나이", "연령", "소득"],
    "내용": ["얼마", "금액", "지원", "혜택", "내용", "기간", "몇", "한도", "개월"],
    "방법": ["어떻게", "방법", "신청", "접수", "서류", "제출", "준비물", "어디"],
    "기간": ["언제", "기간", "마감", "기한", "접수", "모집"],
    "제외": ["제외", "안 되", "안되", "불가", "유의", "주의", "예외", "못"],
}

# 가상 시민 댓글 풀 — 질문 톤에 공감하거나 경험을 보태는 한두 줄짜리 반응.
_CITIZEN_COMMENTS = [
    "저도 같은 게 궁금했어요. 좋은 질문 감사합니다!",
    "지난주에 행정복지센터에 전화해보니 친절하게 안내해 주시더라고요.",
    "서류 준비가 생각보다 간단했어요. 통장 사본이랑 신분증만 챙기시면 돼요.",
    "예산이 빨리 소진된다는 얘기가 있어서 저는 서둘러 신청했습니다.",
    "부모님 대신 신청해 드렸는데 대리 신청도 가능했어요.",
    "온라인이 어려우면 직접 방문하는 게 마음 편하더라고요.",
    "조건이 헷갈리면 신청 전에 한 번 문의해보시는 걸 추천드려요.",
    "저는 자격이 안 돼서 아쉬웠는데, 해당되시면 꼭 받으세요!",
    "공유해 주셔서 감사해요. 주변 친구들한테도 알려줘야겠어요.",
    "후기 보니까 생각보다 빨리 처리된다고 하네요.",
]


def _split_sentences(policy: str) -> list:
    """정책 원문을 문장 단위로 거칠게 분리한다.

    줄바꿈과 마침표(。/.)를 기준으로 나누고, 너무 짧은 조각은 버린다.
    """
    if not policy:
        return []
    # 줄바꿈을 먼저 마침표로 바꿔 한 번에 분리
    text = policy.replace("\n", ". ")
    # 마침표/물음표/느낌표 뒤에서 끊기
    raw = re.split(r"(?<=[.!?。])\s+", text)
    sentences = []
    for s in raw:
        s = s.strip()
        # 대괄호로 묶인 정책 제목 줄([청년 월세 …])은 제외
        if not s or s.startswith("["):
            continue
        if len(s) < 6:
            continue
        sentences.append(s)
    return sentences


def _match_topic(question: str) -> str:
    """질문 문자열에서 가장 많이 매칭되는 주제(대상/내용/방법/기간/제외)를 고른다.

    매칭되는 키워드가 하나도 없으면 빈 문자열을 반환한다.
    """
    q = (question or "").lower()
    best_topic = ""
    best_hits = 0
    for topic, kws in _TOPIC_KEYWORDS.items():
        hits = sum(1 for kw in kws if kw in q)
        if hits > best_hits:
            best_hits = hits
            best_topic = topic
    return best_topic


def _pick_relevant_sentences(policy: str, question: str, k: int = 2) -> list:
    """질문 주제와 가장 관련 있는 정책 문장 k개를 고른다.

    1순위: 질문에 등장한 단어가 직접 포함된 문장.
    2순위: 주제 키워드가 포함된 문장.
    아무것도 못 찾으면 앞쪽 문장으로 대체한다.
    """
    sentences = _split_sentences(policy)
    if not sentences:
        return []

    # 질문에서 의미 있는 토큰(2글자 이상 한글/영문/숫자) 추출
    q_tokens = [t for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", question or "")]

    topic = _match_topic(question)
    topic_kws = _TOPIC_KEYWORDS.get(topic, [])

    scored = []
    for s in sentences:
        score = 0
        # 질문 토큰 직접 매칭(가중치 높음)
        for t in q_tokens:
            if t in s:
                score += 2
        # 주제 키워드 매칭
        for kw in topic_kws:
            if kw in s:
                score += 1
        scored.append((score, s))

    # 점수 내림차순, 점수가 0인 문장은 뒤로
    scored.sort(key=lambda x: x[0], reverse=True)
    picked = [s for sc, s in scored if sc > 0][:k]

    # 관련 문장을 못 찾으면 정책 앞부분으로 대체
    if not picked:
        picked = sentences[:k]
    return picked


def _build_auto_answer(policy: str, question: str) -> str:
    """정책 원문 기반 규칙형 자동답변 문자열을 만든다(mock).

    실제 LLM/RAG 호출 없이, 관련 문장을 골라 안내 문구로 감싼다.
    """
    topic = _match_topic(question)
    relevant = _pick_relevant_sentences(policy, question, k=2)

    # 주제별 도입 문구
    intro_map = {
        "대상": "신청 대상·자격 관련해서 안내드릴게요.",
        "내용": "지원 내용과 금액 관련해서 안내드릴게요.",
        "방법": "신청 방법·절차 관련해서 안내드릴게요.",
        "기간": "신청 기간·일정 관련해서 안내드릴게요.",
        "제외": "제외 대상·유의 사항 관련해서 안내드릴게요.",
    }
    intro = intro_map.get(topic, "문의하신 내용 관련해서 정책 안내를 정리해 드릴게요.")

    if relevant:
        body = "\n".join(f"- {s.rstrip('.')}." for s in relevant)
    else:
        body = "- 현재 등록된 정책 본문에서 관련 안내를 찾지 못했어요."

    outro = (
        "\n\n더 정확한 내용은 거주지 행정복지센터 또는 복지로 누리집에서 "
        "확인해 주세요. (본 답변은 정책 원문을 기반으로 한 자동 안내이며, "
        "실제 심사 결과와 다를 수 있습니다.)"
    )
    return f"{intro}\n\n{body}{outro}"


def _make_comments() -> list:
    """가상 시민 댓글 1~2개를 무작위로 뽑는다(중복 없이)."""
    n = random.randint(1, 2)
    return random.sample(_CITIZEN_COMMENTS, k=n)


def render_board_tab(view):
    """정책 문의 게시판을 그린다.

    상단 폼으로 질문을 입력받아 제출하면, 정책 텍스트 기반 자동답변과
    가상 시민 댓글을 만들어 session_state['board']에 누적한다.
    이후 누적된 Q/A 스레드를 최신순으로 chat_message 형태로 표시한다.
    view가 None이면 안내 후 종료한다.
    """
    # view 없을 때 가드 — 아직 시뮬레이션을 돌리지 않은 상태
    if view is None:
        st.info("아직 시뮬레이션 결과가 없습니다. 정책을 입력하고 시뮬레이션을 실행해 주세요.")
        return

    st.subheader("정책 문의 게시판")
    st.caption(
        "정책에 대해 궁금한 점을 남겨 보세요. 정책 원문을 바탕으로 한 자동 안내와 "
        "가상 시민들의 댓글이 달립니다. (RAG 미연결 — 데모용 자동응답)"
    )

    # 현재 시뮬레이션 대상 정책 원문(자동답변 근거로 사용)
    policy = view.get("policy", "") or ""

    # 게시판 세션 상태 초기화
    if "board" not in st.session_state:
        st.session_state["board"] = []

    # ── 질문 입력 폼 ────────────────────────────────────────────
    with st.form("board_form", clear_on_submit=True):
        nickname = st.text_input("닉네임", value="시민", max_chars=20)
        question = st.text_area(
            "질문 내용",
            placeholder="예) 만 35세도 신청할 수 있나요? 서류는 뭘 준비해야 하죠?",
            height=100,
        )
        submitted = st.form_submit_button("질문 등록")

    if submitted:
        q = (question or "").strip()
        if not q:
            st.warning("질문 내용을 입력해 주세요.")
        else:
            # 자동답변 + 가상 시민 댓글 생성 후 스레드로 누적
            answer = _build_auto_answer(policy, q)
            comments = _make_comments()
            st.session_state["board"].append(
                {
                    "nickname": (nickname or "시민").strip() or "시민",
                    "question": q,
                    "answer": answer,
                    "comments": comments,
                }
            )
            st.success("질문이 등록되었습니다. 아래에서 답변을 확인하세요.")

    st.divider()

    # ── 누적된 Q/A 스레드 표시(최신순) ──────────────────────────
    board = st.session_state.get("board", [])
    if not board:
        st.info("아직 등록된 문의가 없습니다. 첫 질문을 남겨 보세요!")
        return

    # 최신 글이 위로 오도록 역순 순회
    for idx, thread in enumerate(reversed(board)):
        # 질문(시민) 말풍선
        with st.chat_message("user"):
            st.markdown(f"**{thread.get('nickname', '시민')}** 님의 질문")
            st.write(thread.get("question", ""))

        # 자동 안내 답변 말풍선
        with st.chat_message("assistant"):
            st.markdown("**정책 안내 도우미**")
            st.write(thread.get("answer", ""))

        # 가상 시민 댓글들
        for comment in thread.get("comments", []):
            with st.chat_message("user"):
                st.caption("다른 시민의 댓글")
                st.write(comment)

        # 스레드 사이 구분선(마지막 스레드 제외)
        if idx < len(board) - 1:
            st.divider()
