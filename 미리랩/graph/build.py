"""Assemble the StateGraph.  Smoke test: python -m graph.build"""
from langgraph.graph import StateGraph, START, END
from state import SimState
from graph.nodes import react_node, interact_node, aggregate_node


def build_graph():
    g = StateGraph(SimState)
    g.add_node('react', react_node)
    g.add_node('interact', interact_node)
    g.add_node('aggregate', aggregate_node)
    g.add_edge(START, 'react')
    g.add_edge('react', 'interact')
    g.add_edge('interact', 'aggregate')
    g.add_edge('aggregate', END)
    return g.compile()


if __name__ == '__main__':
    app = build_graph()
    print('graph compiled OK:', app)
