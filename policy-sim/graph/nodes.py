"""LangGraph nodes.  Owner: orchestration.

Each node returns a dict that gets merged into SimState.
"""
from state import SimState
from rag.retriever import retrieve


def react_node(state: SimState) -> dict:
    # TODO: for each persona -> retrieve() grounding -> ask LLM for a reaction.
    return {'reactions': []}


def interact_node(state: SimState) -> dict:
    # TODO: each persona sees others' reactions and responds (round 1-2 only).
    return {'interactions': []}


def aggregate_node(state: SimState) -> dict:
    # TODO: summarize conflicts and consensus across reactions.
    return {'summary': ''}
