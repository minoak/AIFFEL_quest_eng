# Policy Reaction Simulator

Multi-agent + RAG simulator: given a policy, stakeholder personas react,
grounded in real group data. Built on the Generative Agents architecture
(Park et al., 2023).

## Setup (3 steps)

1. `git clone <repo-url>` and open the folder in VS Code
2. `pip install -r requirements.txt`
3. Copy `.env.example` to `.env`, paste your OpenAI key, then run `python check.py`

If you see `[OK]`, your environment is ready.

## Run

- Smoke-test the graph: `python -m graph.build`
- Launch the demo: `streamlit run app.py`

## Project layout

- `state.py`  - shared State schema. THE team contract. Do not rename fields alone.
- `rag/`      - persona grounding retrieval (bge-m3 + Chroma)
- `data/`     - persona corpora / source documents
- `graph/`    - LangGraph nodes + assembly (react -> interact -> aggregate)
- `eval/`     - ablation: grounding ON vs OFF
- `app.py`    - Streamlit demo UI
- `notebooks/`- experiments only. NOT imported by app code.

## Rules of the road

- Never commit `.env` (it is gitignored). Never paste a key into code.
- Edit only your own folder. If two people must touch one file, one pushes,
  the other pulls before editing. This avoids merge conflicts.
- All app code is `.py`. Notebooks are for exploration, never imported.
