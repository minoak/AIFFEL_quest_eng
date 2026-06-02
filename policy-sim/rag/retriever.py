"""Persona grounding retrieval.  Owner: data / RAG.

Reuses the existing bge-m3 + Chroma setup.
"""


def retrieve(persona_id: str, policy: str, k: int = 4) -> list:
    # TODO: bge-m3 + Chroma semantic search over this persona's corpus.
    # Should return a list of dicts: {'text': ..., 'source': ...}
    return []
