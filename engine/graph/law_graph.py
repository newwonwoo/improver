"""LawGraph — 법령 corpus 의 조문 간 인용 그래프.

노드: (law_name, article_number) 튜플
엣지:
  - cites_law       : 외부 법령 인용 (law_name → other_law)
  - cites_article   : 외부 법령 조문 인용 (article → 외부 article)
  - internal_ref    : 같은 법령 내부 조문 인용 (article → article)

용도:
  1. SLM 신호 강화 — indegree / outdegree / centrality
  2. Agentic 검증 — suspicious_edges() 로 의심 엣지 추출
  3. 그래프 정제 — prune_edges_by_verdict() 로 검증 결과 반영

설계 원칙:
  - 외부 의존성: networkx 만 (pickle 표준 라이브러리)
  - 캐시: outputs/law_graph.pkl (1회 빌드, 이후 load)
  - 부분 그래프: build_from_law(law) — corpus 빌드 안 한 환경에서도 작동
"""
from __future__ import annotations

import pickle
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

try:
    import networkx as nx  # type: ignore
    _HAS_NX = True
except ImportError:  # pragma: no cover
    _HAS_NX = False
    nx = None  # type: ignore

from ..schema import Article, Law
from ..structure import ArticleDecomposition, decompose


DEFAULT_CACHE_PATH = Path("outputs/law_graph.pkl")
_LAWS_DIR = Path("data/laws/raw")

# 같은 법령 내 internal_ref 추출용 (engine/structure._INTERNAL_ARTICLE_RX 와 동치)
_INTERNAL_RX = re.compile(r"제(\d+)조(?:의(\d+))?(?:제(\d+)항)?")
# 외부 법령 인용: 「법령명」 제N조
_CITED_ARTICLE_RX = re.compile(r"「([^」]+)」\s*제(\d+)조(?:의(\d+))?(?:\s*제\d+항)?")


@dataclass
class GraphSignals:
    """단일 article 의 그래프 기반 신호."""
    indegree: int = 0       # 다른 article 이 본 article 을 인용한 횟수
    outdegree: int = 0      # 본 article 이 다른 article 을 인용한 횟수
    indegree_norm: float = 0.0
    outdegree_norm: float = 0.0
    centrality_norm: float = 0.0   # betweenness centrality (cached)
    pagerank_norm: float = 0.0     # PageRank (영향 반경 — CodeGraph impact analysis 착안)

    def to_dict(self) -> dict[str, float]:
        return {
            "graph_indegree_norm": self.indegree_norm,
            "graph_outdegree_norm": self.outdegree_norm,
            "graph_centrality_norm": self.centrality_norm,
            "graph_pagerank_norm": self.pagerank_norm,
        }


def _node(law: str, article_number: str) -> tuple[str, str]:
    return (law, article_number)


def _article_key(art: Article) -> str:
    """Article → 안정적인 article key (number 우선, fallback raw)."""
    return art.number or ""


@dataclass
class LawGraph:
    """법령 corpus 의 조문 인용 그래프."""

    G: "nx.DiGraph" = field(default_factory=lambda: nx.DiGraph() if _HAS_NX else None)
    # centrality cache (computed lazily on demand; sampled for performance)
    _centrality_cache: dict[tuple[str, str], float] = field(default_factory=dict)
    _centrality_built: bool = False
    # pagerank cache (1회 전체 계산 후 정규화 저장)
    _pagerank_cache: dict[tuple[str, str], float] = field(default_factory=dict)

    # === build ===
    @classmethod
    def empty(cls) -> "LawGraph":
        if not _HAS_NX:
            raise RuntimeError("networkx is required for LawGraph")
        return cls(G=nx.DiGraph())

    @classmethod
    def from_law(cls, law: Law) -> "LawGraph":
        """단일 법령으로부터 부분 그래프 빌드 (corpus cache 없을 때 fallback)."""
        g = cls.empty()
        g._add_law_nodes(law)
        g._add_law_edges(law, only_internal=True)
        return g

    @classmethod
    def from_corpus(
        cls,
        laws_dir: Path | str = _LAWS_DIR,
        limit: int | None = None,
        verbose: bool = False,
    ) -> "LawGraph":
        """전체 corpus 로부터 그래프 빌드 (느림 — 1회 빌드 후 save 권장).

        limit: 디버깅용 (상위 N 법령만).
        """
        from ..parser import parse_law

        g = cls.empty()
        laws_dir = Path(laws_dir)
        loaded: list[Law] = []
        for i, law_path in enumerate(sorted(laws_dir.iterdir())):
            if limit is not None and i >= limit:
                break
            md = law_path / "법률.md"
            if not md.exists():
                continue
            try:
                text = md.read_text(encoding="utf-8")
            except OSError:
                continue
            try:
                law = parse_law(text, name=law_path.name)
            except Exception:
                continue
            loaded.append(law)
            g._add_law_nodes(law)
            if verbose and i % 100 == 0:
                print(f"  build nodes: {i+1} laws, {g.G.number_of_nodes()} nodes")

        # 2nd pass: 엣지는 모든 노드가 있어야 cross-law cited_articles 연결 가능
        for law in loaded:
            g._add_law_edges(law, only_internal=False)
        if verbose:
            print(f"  done: {g.G.number_of_nodes()} nodes, {g.G.number_of_edges()} edges")
        return g

    def _add_law_nodes(self, law: Law) -> None:
        law_name = law.name
        for art in law.articles:
            self.G.add_node(
                _node(law_name, _article_key(art)),
                law=law_name,
                title=art.title or "",
            )

    def _add_law_edges(self, law: Law, *, only_internal: bool) -> None:
        law_name = law.name
        for art in law.articles:
            src = _node(law_name, _article_key(art))
            if not self.G.has_node(src):
                continue
            text = art.full_text
            # 외부 법령 인용 — cites_article (해당 외부 법령의 노드가 있는 경우만)
            if not only_internal:
                for m in _CITED_ARTICLE_RX.finditer(text):
                    other_law = m.group(1).strip()
                    other_num = f"제{m.group(2)}조"
                    if m.group(3):
                        other_num = f"제{m.group(2)}조의{m.group(3)}"
                    dst = _node(other_law, other_num)
                    if self.G.has_node(dst):
                        self.G.add_edge(src, dst, kind="cites_article")
            # 내부 조문 인용 — internal_ref
            # 외부 법령 부분 제거 후 internal 만 추출 (engine/structure 와 동일 패턴)
            text_internal = _CITED_ARTICLE_RX.sub("", text)
            for m in _INTERNAL_RX.finditer(text_internal):
                num = f"제{m.group(1)}조"
                if m.group(2):
                    num = f"제{m.group(1)}조의{m.group(2)}"
                dst = _node(law_name, num)
                if dst == src:
                    continue
                if self.G.has_node(dst):
                    self.G.add_edge(src, dst, kind="internal_ref")

    # === query ===
    def signals_for(
        self,
        law_name: str,
        article_number: str,
        *,
        compute_centrality: bool = False,
    ) -> GraphSignals:
        """단일 article 에 대한 그래프 신호."""
        node = _node(law_name, article_number)
        if not self.G.has_node(node):
            return GraphSignals()
        indeg = self.G.in_degree(node)
        outdeg = self.G.out_degree(node)
        # 정규화 — 상위 quantile 캡 사용 (deg 20 이상 = 1.0)
        signals = GraphSignals(
            indegree=indeg,
            outdegree=outdeg,
            indegree_norm=min(indeg / 20.0, 1.0),
            outdegree_norm=min(outdeg / 20.0, 1.0),
        )
        if compute_centrality:
            signals.centrality_norm = self._centrality_for(node)
        signals.pagerank_norm = self._pagerank_for(node)
        return signals

    def _pagerank_for(self, node: tuple[str, str]) -> float:
        """PageRank 기반 영향 반경 신호 (CodeGraph impact analysis 착안).

        degree 보다 전이적 중요도(허브 조문)를 잘 포착. 1회 계산 후 캐시.
        max 값으로 정규화 → [0,1].
        """
        if not self._pagerank_cache:
            try:
                pr = nx.pagerank(self.G, alpha=0.85, max_iter=30, tol=1e-4)
            except Exception:
                pr = {}
            mx = max(pr.values()) if pr else 1.0
            # max 정규화 (희소 분포라 sqrt 스케일로 분해능 확보)
            import math
            self._pagerank_cache = {
                k: min(math.sqrt(v / mx) if mx > 0 else 0.0, 1.0)
                for k, v in pr.items()
            }
        return self._pagerank_cache.get(node, 0.0)

    def _centrality_for(self, node: tuple[str, str]) -> float:
        """Lazy centrality — degree-centrality 기반 (betweenness 는 12만 노드에서 비실용).

        normalized in-degree (corpus-wide percentile) 활용.
        """
        if node not in self._centrality_cache:
            n = self.G.number_of_nodes()
            if n <= 1:
                return 0.0
            indeg = self.G.in_degree(node)
            # degree centrality (in) — n-1 로 나눈 후 캡 적용
            cent = min(indeg / max(n - 1, 1) * 100, 1.0)  # 매우 sparse → scale up x100
            self._centrality_cache[node] = cent
        return self._centrality_cache[node]

    def suspicious_edges(
        self,
        *,
        top: int = 50,
        kinds: tuple[str, ...] = ("cites_article", "internal_ref"),
    ) -> list[tuple[tuple[str, str], tuple[str, str], str]]:
        """검증 가치 높은 엣지 추출 — Agentic 6a 입력.

        휴리스틱: 인용 횟수 1회만 등장 (sparsest 신호) + cross-law 엣지 우선.
        반환: [(src, dst, kind), ...] top-N.
        """
        edges = [
            (u, v, d.get("kind", "?"))
            for u, v, d in self.G.edges(data=True)
            if d.get("kind") in kinds
        ]
        # cross-law 우선 (cites_article), 그 다음 internal_ref
        def _score(edge: tuple) -> tuple[int, int]:
            u, v, kind = edge
            cross_law = 0 if u[0] != v[0] else 1
            return (cross_law, self.G.in_degree(v))
        edges.sort(key=_score)
        return edges[:top]

    def prune_edges_by_verdict(self, rejected: Iterable[tuple[tuple[str, str], tuple[str, str]]]) -> int:
        """Agentic 검증으로 false-positive 으로 판명된 엣지 제거.

        Returns 제거된 엣지 수.
        """
        removed = 0
        for u, v in rejected:
            if self.G.has_edge(u, v):
                self.G.remove_edge(u, v)
                removed += 1
        # centrality 캐시 invalidate
        self._centrality_cache.clear()
        return removed

    # === persistence ===
    def save(self, path: Path | str = DEFAULT_CACHE_PATH) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("wb") as f:
            pickle.dump({"G": self.G}, f)
        return path

    @classmethod
    def load(cls, path: Path | str = DEFAULT_CACHE_PATH) -> "LawGraph | None":
        path = Path(path)
        if not path.exists():
            return None
        try:
            with path.open("rb") as f:
                data = pickle.load(f)
        except (pickle.PickleError, OSError, EOFError):
            return None
        return cls(G=data["G"])

    def stats(self) -> dict[str, int]:
        return {
            "nodes": self.G.number_of_nodes(),
            "edges": self.G.number_of_edges(),
            "internal_ref_edges": sum(
                1 for _, _, d in self.G.edges(data=True)
                if d.get("kind") == "internal_ref"
            ),
            "cites_article_edges": sum(
                1 for _, _, d in self.G.edges(data=True)
                if d.get("kind") == "cites_article"
            ),
        }


# === module-level cached graph (singleton) ===
_CACHED: LawGraph | None = None


def get_cached_graph() -> LawGraph | None:
    """corpus cache 가 있으면 lazy load, 없으면 None."""
    global _CACHED
    if _CACHED is None:
        _CACHED = LawGraph.load()
    return _CACHED


def graph_signals_for_article(
    law: Law,
    art: Article,
    decomp: ArticleDecomposition | None = None,
) -> GraphSignals:
    """SLM feature extraction 에서 호출하는 헬퍼.

    우선순위:
      1. corpus cache 있으면 사용
      2. 없으면 단일 법령 from_law 부분 그래프 (per-article 호출시 캐시 필요 → law-level 캐시)
      3. networkx 없으면 zero signals
    """
    if not _HAS_NX:
        return GraphSignals()
    graph = get_cached_graph()
    if graph is None:
        # per-law 부분 그래프 — Law 객체에 캐시
        graph = getattr(law, "_law_graph_cache", None)
        if graph is None:
            graph = LawGraph.from_law(law)
            try:
                setattr(law, "_law_graph_cache", graph)
            except (AttributeError, TypeError):
                pass
    return graph.signals_for(law.name, _article_key(art))
