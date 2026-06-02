"""정책 입력/확인 탭.

현재 시뮬레이션 대상 정책의 원문을 보여주고, 정책 텍스트에서
핵심 정보(대상/혜택/신청 방법/기간)를 간단히 추출해 4칸으로 정리한다.

공개 API: render_input_tab(view)
- view: ui/model.py:build_view(sim) 가 만든 ViewModel(dict) 또는 None
- view 가 None 이면 안내만 표시하고 종료.

추출 전략(MVP, 외부 호출 없음):
- 정책 원문은 sample_policies.py 형식("신청 대상:", "지원 내용:", "신청 방법:",
  "신청 기간:" 같은 라벨 줄)을 따른다는 가정 아래 라벨 매칭으로 뽑는다.
- 라벨이 없으면 첫 문장/안내 문구로 대체한다(빈 칸을 만들지 않는다).
"""
import re

import streamlit as st


# ── 추출용 라벨 사전 ────────────────────────────────────────────────
# 각 핵심 항목마다 "정책 원문에 나올 법한 라벨 후보"들을 나열한다.
# 위에 있는 후보일수록 우선순위가 높다(먼저 매칭되면 그걸 쓴다).
_LABELS: dict[str, list[str]] = {
    "대상": ["신청 대상", "지원 대상", "대상", "수혜 대상"],
    "혜택": ["지원 내용", "지원 금액", "혜택", "급여 내용", "지원"],
    "신청 방법": ["신청 방법", "신청 방식", "접수 방법", "신청 절차"],
    "기간": ["신청 기간", "접수 기간", "지원 기간", "사용 기한", "기간"],
}

# 각 칸 헤더에 붙일 이모지(아이콘) — 시각적 구분용.
_ICONS: dict[str, str] = {
    "대상": "👥",
    "혜택": "💰",
    "신청 방법": "📝",
    "기간": "📅",
}


def _get_policy_text(view) -> str:
    """ViewModel에서 정책 원문 문자열을 안전하게 꺼낸다.

    build_view 의 정확한 키 구조에 의존하지 않도록 여러 후보 키를 순서대로 탐색한다.
    """
    if view is None:
        return ""
    if isinstance(view, str):
        return view.strip()
    if not isinstance(view, dict):
        return str(view).strip()

    # 1) 평탄한 최상위 키 후보
    for key in ("policy", "policy_text", "정책", "정책원문"):
        val = view.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()

    # 2) 중첩 dict(예: view['input'], view['meta']) 안의 policy
    for outer in ("input", "meta", "sim", "state"):
        inner = view.get(outer)
        if isinstance(inner, dict):
            for key in ("policy", "policy_text", "정책"):
                val = inner.get(key)
                if isinstance(val, str) and val.strip():
                    return val.strip()
    return ""


def _split_lines(policy: str) -> list[str]:
    """정책 원문을 의미 단위 줄로 분해한다.

    sample_policies 는 '\\n' 으로 라벨 항목을 한 줄씩 나누므로 줄바꿈 분해만으로 충분하다.
    다만 한 줄에 '... 문장. 신청 방법: ...' 처럼 라벨이 문장 중간에 끼어 있는 경우를 대비해,
    '라벨:' 의 라벨 전체(2~6자 한글 + 선택적 공백)가 통째로 보존되도록 끊어 준다.
    """
    raw = [ln.strip() for ln in policy.splitlines() if ln.strip()]
    out: list[str] = []
    # 라벨 후보 전체를 정규식 대안으로 묶어, 라벨 시작 직전에서만 분리한다.
    all_labels = sorted(
        {c for cands in _LABELS.values() for c in cands}, key=len, reverse=True
    )
    label_alt = "|".join(re.escape(c) for c in all_labels)
    splitter = re.compile(r"(?<!^)(?=(?:" + label_alt + r")\s*[:：])")
    for ln in raw:
        parts = splitter.split(ln)
        for p in parts:
            p = p.strip()
            if p:
                out.append(p)
    return out or [policy.strip()]


def _extract_field(lines: list[str], candidates: list[str]) -> str:
    """라벨 후보들에 매칭되는 줄에서 값(라벨 뒤 텍스트)을 뽑는다.

    매칭 실패 시 빈 문자열을 돌려준다.
    """
    for cand in candidates:
        # "라벨:" 또는 "라벨 :" 형태를 줄 앞쪽에서 찾는다.
        pat = re.compile(r"^\s*\[?\s*" + re.escape(cand) + r"\s*\]?\s*[:：]\s*(.+)")
        for ln in lines:
            m = pat.match(ln)
            if m:
                value = m.group(1).strip()
                if value:
                    return value
    return ""


def _extract_core(policy: str) -> dict[str, str]:
    """정책 원문에서 핵심 4항목을 추출. 실패한 칸은 빈 문자열로 둔다."""
    lines = _split_lines(policy)
    core: dict[str, str] = {}
    for field, candidates in _LABELS.items():
        core[field] = _extract_field(lines, candidates)
    return core


def render_input_tab(view) -> None:
    """정책 입력/확인 탭 렌더링."""
    if view is None:
        st.info("좌측 사이드바에서 정책을 선택/입력하고 시뮬레이션을 실행하세요")
        return

    policy = _get_policy_text(view)

    st.subheader("📄 시뮬레이션 대상 정책")

    if not policy:
        # view 는 있는데 정책 텍스트를 못 찾은 예외 상황
        st.warning("정책 원문을 찾을 수 없습니다. 좌측 사이드바에서 정책을 선택/입력해 주세요.")
        return

    # ── 정책 원문 ────────────────────────────────────────────────
    # 제목 줄([...])이 있으면 마크다운 제목으로, 나머지는 본문으로 보여 준다.
    lines = [ln.strip() for ln in policy.splitlines() if ln.strip()]
    title = ""
    body = policy
    if lines and lines[0].startswith("[") and lines[0].endswith("]"):
        title = lines[0].strip("[]").strip()
        body = "\n".join(lines[1:]).strip()

    if title:
        st.markdown(f"### {title}")

    with st.expander("정책 원문 전체 보기", expanded=True):
        # 줄바꿈을 그대로 유지해 읽기 좋게 표시
        st.markdown(body.replace("\n", "  \n"))

    st.divider()

    # ── 핵심 정보 4칸 ────────────────────────────────────────────
    st.markdown("#### 🔑 핵심 정보 요약")
    st.caption("정책 원문에서 자동 추출했습니다. 일부 항목은 원문에 라벨이 없으면 비어 있을 수 있습니다.")

    core = _extract_core(policy)
    fields = ["대상", "혜택", "신청 방법", "기간"]
    cols = st.columns(4)
    for col, field in zip(cols, fields):
        with col:
            icon = _ICONS.get(field, "•")
            st.markdown(f"**{icon} {field}**")
            value = core.get(field, "")
            if value:
                # 너무 길면 보기 좋게 잘라서 표시(전체는 아래 원문/expander에서 확인)
                shown = value if len(value) <= 160 else value[:158] + "…"
                st.write(shown)
            else:
                st.caption("원문에서 자동 추출 실패 — 위 정책 원문을 직접 확인하세요.")

    # ── 추출 실패 항목 안내 ──────────────────────────────────────
    missing = [f for f in fields if not core.get(f)]
    if missing:
        st.info(
            "다음 항목은 정책 원문에서 자동으로 찾지 못했습니다: "
            + ", ".join(missing)
            + ". 정책 원문에 '신청 대상:', '지원 내용:', '신청 방법:', '신청 기간:' 같은 "
            "라벨 줄을 추가하면 더 정확히 추출됩니다."
        )
