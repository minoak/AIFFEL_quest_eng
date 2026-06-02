# 정책 반응 시뮬레이터

다중 에이전트 + RAG 시뮬레이터: 정책이 주어지면 이해관계자 페르소나가 반응합니다.
실제 그룹 데이터를 기반으로 하며, 생성형 에이전트 아키텍처(Generative Agents architecture)를 사용합니다.
(Park et al., 2023)

## 설정 (3단계)

1. `git clone <repo-url>` 명령어를 실행하고 VS Code에서 폴더를 엽니다.
2. `pip install -r requirements.txt` 명령어를 실행합니다.

3. `.env.example` 파일을 `.env` 파일로 복사하고 OpenAI 키를 붙여넣은 후 `python check.py`를 실행합니다.

`[OK]`가 표시되면 환경 설정이 완료된 것입니다.

## 실행

- 그래프 스모크 테스트: `python -m graph.build`
- 데모 실행: `streamlit run app.py`

## 프로젝트 구조

- `state.py` - 공유 상태 스키마 파일입니다. 팀 전체의 약속이므로 필드 이름을 임의로 변경하지 마십시오.

- `rag/` - 페르소나 그라운딩 검색(bge-m3 + Chroma)
- `data/` - 페르소나 코퍼스/원본 문서
- `graph/` - LangGraph 노드 + 어셈블리(React -> Interact -> Aggregate)
- `eval/` - 어블레이션: 그라운딩 켜기/끄기
- `app.py` - Streamlit 데모 UI
- `notebooks/` - 실험용 폴더. 앱 코드에서 가져오지 마세요.

## 규칙

- `.env` 파일은 절대 커밋하지 마세요(gitignore에 포함되어 있습니다). 코드에 키를 붙여넣지 마세요.

- 자신의 폴더만 수정하세요. 두 사람이 같은 파일을 수정해야 하는 경우, 한 사람은 푸시하고,

다른 사람은 수정하기 전에 풀하세요. 이렇게 하면 병합 충돌을 방지할 수 있습니다.

- 모든 앱 코드는 `.py` 파일입니다. 노트북은 탐색용이며, 앱 코드에서 가져오지 마세요.
