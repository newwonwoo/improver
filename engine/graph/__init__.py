"""GraphRAG-lite — 법령 신호 그래프.

조문 간 관계(cited_laws / cited_articles / internal_refs)를 networkx DiGraph 로
명시화. SLM 신호로 graph_indegree / graph_outdegree / graph_centrality 제공.

Phase 4 (docs/PHASE4_GRAPH.md): article F1 보강 + centrality 차원.
"""
from .law_graph import (
    LawGraph,
    GraphSignals,
    graph_signals_for_article,
    DEFAULT_CACHE_PATH,
)

__all__ = [
    "LawGraph",
    "GraphSignals",
    "graph_signals_for_article",
    "DEFAULT_CACHE_PATH",
]
