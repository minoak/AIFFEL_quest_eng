"""채팅(전파) 탭 — SNS 채팅방 느낌으로 전파 라운드를 보여준다.

view['interactions'] (전파 메시지 목록)를 round별로 묶어서
턴 구분 헤더 + 발화자별 채팅 버블로 렌더링한다.
발화자 이름/요약은 view['personas']에서 from_id로 매핑한다.

공개 API: render_chat_tab(view)
- view 가 None 이면 안내만 표시하고 종료한다(아직 시뮬레이션 전).
"""
import streamlit as st


# ── 카카오톡 느낌의 가벼운 CSS (한 번만 주입) ─────────────────────────────
_CHAT_CSS = """
<style>
/* 전파 채팅방 영역: 살짝 카톡스러운 배경/말풍선 톤 */
.miri-chat-wrap { background:#b2c7d9; border-radius:14px;
    padding:14px 10px 6px 10px; margin:6px 0 18px 0; }
.miri-turn-sep { text-align:center; margin:10px 0 6px 0; }
.miri-turn-sep span { background:rgba(0,0,0,0.18); color:#fff;
    font-size:0.78rem; padding:3px 12px; border-radius:12px; }
/* st.chat_message 기본 말풍선을 카톡 노란/흰 톤으로 살짝 보정 */
.miri-chat-wrap [data-testid="stChatMessage"] { background:transparent; }
.miri-stance { font-size:0.74rem; opacity:0.75; margin-left:6px; }
.miri-shift { font-size:0.74rem; color:#c0392b; margin-left:6px; }
</style>
"""

# 입장(stance) → 한글 라벨 + 이모지 (반응 카드와 톤 통일)
_STANCE_LABEL = {
    'support': '👍 찬성',
    'oppose': '👎 반대',
    'mixed': '🤔 중립',
}

# 입장 → 아바타 이모지 (발화자 표정으로 분위기 전달)
_STANCE_AVATAR = {
    'support': '🙂',
    'oppose': '😠',
    'mixed': '😐',
}


def _build_persona_index(view):
    """view['personas']를 id -> persona dict 로 인덱싱한다.

    personas 가 list[Persona] 든 dict({id:persona}) 든 모두 받아준다.
    매핑 실패에 대비해 항상 dict 를 반환한다.
    """
    personas = (view or {}).get('personas')
    index = {}
    if isinstance(personas, dict):
        # 이미 id 키 형태면 그대로 사용
        for pid, p in personas.items():
            if isinstance(p, dict):
                index[str(pid)] = p
    elif isinstance(personas, (list, tuple)):
        for p in personas:
            if isinstance(p, dict) and p.get('id') is not None:
                index[str(p['id'])] = p
    return index


def _speaker_name(persona, from_id):
    """발화자 표시 이름. 페르소나를 못 찾으면 id 일부로 대체."""
    if isinstance(persona, dict):
        name = persona.get('name')
        if name:
            return str(name)
    # 폴백: id 앞 6자
    fid = str(from_id) if from_id is not None else '익명'
    return f'시민 {fid[:6]}'


def _speaker_meta(persona):
    """버블 옆에 곁들일 한 줄 요약(있으면). 길면 잘라준다."""
    if isinstance(persona, dict):
        desc = persona.get('description')
        if desc:
            desc = str(desc)
            return desc if len(desc) <= 40 else desc[:39] + '…'
    return ''


def _avatar_for(persona, msg):
    """아바타 이모지: 페르소나의 마지막 입장(stance_shift) 우선, 없으면 표정."""
    shift = (msg or {}).get('stance_shift')
    if shift in _STANCE_AVATAR:
        return _STANCE_AVATAR[shift]
    # 페르소나에 stance 힌트가 있으면 사용
    if isinstance(persona, dict):
        st_hint = persona.get('stance')
        if st_hint in _STANCE_AVATAR:
            return _STANCE_AVATAR[st_hint]
    return '🗨️'


def _group_by_round(interactions):
    """interactions 를 round 오름차순으로 묶는다. round 없으면 0으로."""
    groups = {}
    for it in interactions:
        if not isinstance(it, dict):
            continue
        r = it.get('round', 0)
        try:
            r = int(r)
        except (TypeError, ValueError):
            r = 0
        groups.setdefault(r, []).append(it)
    # round 키 오름차순으로 (round, 메시지목록) 리스트 반환
    return [(r, groups[r]) for r in sorted(groups.keys())]


def render_chat_tab(view):
    """전파(채팅) 탭 본체.

    Parameters
    ----------
    view : dict | None
        ui.model.build_view(sim) 결과. None 이면 아직 시뮬레이션 전.
    """
    # ── None 가드: 시뮬레이션 결과가 없으면 안내만 ──────────────────────
    if view is None:
        st.info('아직 시뮬레이션 결과가 없어요. 먼저 정책을 입력하고 시뮬레이션을 실행해 주세요.')
        return

    st.subheader('💬 전파 채팅방')
    st.caption('시민들이 서로의 반응을 보고 주고받은 메시지를 라운드(턴)별로 보여줘요.')

    interactions = view.get('interactions') or []
    if not isinstance(interactions, (list, tuple)) or len(interactions) == 0:
        st.info('아직 전파(상호작용) 메시지가 없어요. 전파 라운드를 1회 이상 돌리면 여기에 대화가 나타나요.')
        return

    # 가벼운 카톡풍 CSS 주입
    st.markdown(_CHAT_CSS, unsafe_allow_html=True)

    persona_index = _build_persona_index(view)
    rounds = _group_by_round(interactions)

    for r, msgs in rounds:
        # 턴 구분 헤더
        st.subheader(f'{r}턴')

        # 채팅방 배경 래퍼 시작
        st.markdown('<div class="miri-chat-wrap">', unsafe_allow_html=True)

        for msg in msgs:
            from_id = msg.get('from_id')
            persona = persona_index.get(str(from_id)) if from_id is not None else None

            name = _speaker_name(persona, from_id)
            avatar = _avatar_for(persona, msg)
            text = (msg.get('text') or '').strip()
            if not text:
                continue

            # st.chat_message 로 발화자 버블 표시
            with st.chat_message(name=name, avatar=avatar):
                # 발화자 이름 + 한 줄 요약 헤더
                meta = _speaker_meta(persona)
                header = f'**{name}**'
                if meta:
                    header += f' <span class="miri-stance">{meta}</span>'
                st.markdown(header, unsafe_allow_html=True)

                # 본문 메시지
                st.write(text)

                # 입장 변화가 있으면 작게 표기
                shift = msg.get('stance_shift')
                if shift:
                    label = _STANCE_LABEL.get(shift, shift)
                    st.markdown(
                        f'<span class="miri-shift">↪ 입장 변화: {label}</span>',
                        unsafe_allow_html=True,
                    )

        # 채팅방 배경 래퍼 끝
        st.markdown('</div>', unsafe_allow_html=True)
