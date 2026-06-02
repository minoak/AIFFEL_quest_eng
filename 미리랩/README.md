# 미리랩 (MiriLab) — 정책 반응 시뮬레이터

> 정책이 시민에게 배포되기 **전에**, AI 가상 시민 사회에서 **미리** 반응을 실험하는 시뮬레이터.

정부·지자체 정책을 입력하면, 실제 한국 인구통계 기반 합성 페르소나(시민) 약 24명이 각자의
상황(나이·소득·디지털 리터러시·거주지 등)에 따라 정책에 반응합니다. 그 반응을 모아
**사회 혼란도 / 정책 수용도 / 신청 의향**을 수치화하고, 정보 전파 경로와 개선안(쉬운글 변환 포함)을
보여줍니다.

다중 에이전트 + 생성형 에이전트 아키텍처(Generative Agents, Park et al. 2023) 기반.

---

## 핵심 기능

- **실제 인구통계 기반 시민**: `nvidia/Nemotron-Personas-Korea`(통계청·대법원·건보공단 등 기반 합성 페르소나)에서 샘플링
- **시민별 반응 + 5축 점수**: 이해도 / 수혜 가능성 / 신청 의향 / 불만도 / 공유 가능성 (0~100)
- **감성 대시보드**: 사회 혼란도·정책 수용도·신청 의향 지수 게이지
- **SNS형 채팅방 + 전파 네트워크 그래프**: 시민 간 정보가 퍼지는 과정 시각화
- **개선 제안**: 정책 쉬운글 변환 + 구체적 개선안 자동 생성
- **AB 테스트 / 게시판**: 정책 수정 전후 비교, 문의 자동 답변
- **신뢰성 검증(ablation)**: 페르소나 grounding ON/OFF 비교
- **데모 모드**: OpenAI 키 없이도 mock 데이터로 전체 UI 시연 가능

---

## 빠른 시작

### 1. 설치
```powershell
pip install -r requirements.txt
```

### 2. (선택) OpenAI 키 설정 — 실제 모드로 돌릴 때만 필요
`.env.example` 을 복사해 `.env` 를 만들고 키를 채웁니다.
```powershell
copy .env.example .env
# .env 를 열어 OPENAI_API_KEY 에 본인 키 입력
```
키가 올바른지 점검:
```powershell
python check.py    # [OK] 가 뜨면 준비 완료
```

### 3. 실행
```powershell
streamlit run app.py
```
> `streamlit` 명령이 PATH에 없다는 에러가 나면: **`python -m streamlit run app.py`** 로 실행하세요.
> Windows에서는 **PowerShell**을 권장합니다(Git Bash는 `\` 경로 처리 문제가 있을 수 있음).

브라우저가 열리면 → 왼쪽 사이드바에서 정책 선택 → `시뮬레이션 실행` 클릭.

---

## 실행 모드

| 모드 | 조건 | 동작 |
|---|---|---|
| **데모 모드** | 사이드바 `데모 모드` 체크 (키 없으면 자동) | mock 데이터로 전체 UI 시연. 네트워크·키 불필요. 발표 안전망. |
| **실제 모드** | `데모 모드` 해제 + `.env` 에 유효한 키 | OpenAI LLM 호출 + 실제 Nemotron 페르소나로 시뮬레이션 |

> 실제 모드 첫 실행 시 페르소나 데이터셋의 parquet 1개(~220MB)를 한 번 내려받아
> `data/personas_cache.json` 에 샘플을 캐시합니다. 이후 실행은 캐시를 재사용합니다(오프라인 가능).

---

## 프로젝트 구조

```
app.py                  # Streamlit 진입점 (사이드바 + 탭 오케스트레이션)
state.py                # 공유 상태 스키마 = 팀 약속 (필드명 변경 금지, 추가만)
sample_policies.py      # 샘플 정책 3종 (청년 월세 / 어르신 디지털 / 첫만남 이용권)
prompts.py              # 한글 프롬프트 빌더 (react / interact / aggregate)
check.py                # OpenAI 키 점검

data/personas.py        # Nemotron 페르소나 샘플링 + 매핑 + 캐시
graph/
  build.py              # LangGraph 조립 (react → interact → aggregate)
  nodes.py              # 노드 구현 + 구조화 출력 스키마
  llm.py                # OpenAI 클라이언트 + 구조화 호출 + 스레드 동시 실행
  sentiment.py          # 감성 점수 (LLM 기반, KoBERT 훅 옵션)
eval/ablation.py        # grounding ON/OFF 비교 검증
rag/retriever.py        # (옵션) 긴 정책용 RAG — MVP 미사용

viz.py                  # 시각화 (게이지·반응 카드·전파 그래프·채팅 버블)
ui/
  state_helpers.py      # 시뮬레이션 실행 + 캐싱 + 데모 폴백
  model.py              # SimState → 화면용 ViewModel 변환
  mock.py               # 데모용 가짜 SimState (키 없이 동작)
  tab_*.py              # 탭별 렌더링 (정책입력/대시보드/채팅/네트워크/개선/AB/게시판)
```

---

## 데이터셋 / 모델

- 페르소나: [`nvidia/Nemotron-Personas-Korea`](https://huggingface.co/datasets/nvidia/Nemotron-Personas-Korea) (CC BY 4.0, 자동 다운로드)
- LLM: OpenAI `gpt-4o-mini` (기본)
- 임베딩(옵션 RAG): OpenAI `text-embedding-3-small`

---

## 주의사항

- **`.env` 는 절대 커밋하지 마세요** (`.gitignore` 에 포함됨). 키를 코드에 직접 넣지 마세요.
- `state.py` 의 기존 필드명은 바꾸지 마세요(팀 공유 계약). 새 필드는 추가만.
- 노트북(`notebooks/`)은 탐색용이며 앱 코드에서 import 하지 마세요.

---

## 레퍼런스

- Generative Agents: Interactive Simulacra of Human Behavior (Park et al., 2023) — https://arxiv.org/abs/2304.03442
- RAG for Knowledge-Intensive NLP Tasks (Lewis et al., 2020) — https://arxiv.org/abs/2005.11401
- LangGraph — https://langchain-ai.github.io/langgraph
- Streamlit — https://streamlit.io
