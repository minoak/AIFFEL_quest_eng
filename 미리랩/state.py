"""Shared State schema = the team contract.

This is the interface between rag/, graph/, eval/, and app.py.
Do NOT rename fields without telling the whole team first.
Every module reads/writes these exact keys.
"""
from typing import TypedDict, Annotated
from operator import add


class Persona(TypedDict):
    id: str            # 'youth' | 'self_employed' | 'union' | 'business' ...
    name: str          # display name for the UI
    description: str   # short stance / interests summary
    sources: list      # grounding doc ids/notes (filled by rag/)


class Reaction(TypedDict):
    persona_id: str
    stance: str        # 'support' | 'oppose' | 'mixed'
    text: str          # the generated reaction
    evidence: list     # retrieved snippets used to ground the reaction


class SimState(TypedDict):
    policy: str                          # the policy under simulation
    personas: list                       # list[Persona]
    reactions: Annotated[list, add]      # list[Reaction] - nodes append here
    interactions: Annotated[list, add]   # cross-persona replies (round 1-2)
    summary: str                         # aggregated conflict / consensus
