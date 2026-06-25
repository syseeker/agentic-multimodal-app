"""GPU graph analytics over the case network (RAPIDS cuGraph).

Centrality -> the "key player". Community detection -> cells/clusters.
Degrades to NetworkX on CPU if cuGraph/cudf are unavailable (e.g. arm64 wheel
gaps on GB10) so the app never hard-fails on the analytics layer.
"""
from __future__ import annotations

from .falkor import edgelist


def _try_cugraph(edges: list[tuple[str, str]]):
    import cudf
    import cugraph

    df = cudf.DataFrame(edges, columns=["src", "dst"])
    G = cugraph.Graph(directed=True)
    G.from_cudf_edgelist(df, source="src", destination="dst")

    pr = cugraph.pagerank(G).sort_values("pagerank", ascending=False)
    key_players = [
        {"id": row["vertex"], "score": float(row["pagerank"])}
        for _, row in pr.head(5).to_pandas().iterrows()
    ]
    parts = cugraph.louvain(G.to_undirected())[0].to_pandas()
    communities = [
        {"community": int(c), "members": grp["vertex"].tolist()}
        for c, grp in parts.groupby("partition")
    ]
    return key_players, communities, "cugraph"


def _networkx(edges: list[tuple[str, str]]):
    import networkx as nx

    G = nx.DiGraph()
    G.add_edges_from(edges)
    if G.number_of_nodes() == 0:
        return [], [], "networkx"
    try:
        ranking = nx.pagerank(G)            # needs scipy
    except (ImportError, ModuleNotFoundError):
        ranking = nx.degree_centrality(G)   # scipy-free fallback
    key_players = [
        {"id": k, "score": float(v)}
        for k, v in sorted(ranking.items(), key=lambda x: -x[1])[:5]
    ]
    communities = [
        {"community": i, "members": list(c)}
        for i, c in enumerate(nx.community.greedy_modularity_communities(G.to_undirected()))
    ]
    return key_players, communities, "networkx"


def analyze(case_id: str) -> dict:
    edges = edgelist(case_id)
    if not edges:
        return {"key_players": [], "communities": [], "engine": "none"}
    try:
        kp, comm, engine = _try_cugraph(edges)
    except Exception:
        kp, comm, engine = _networkx(edges)
    return {"key_players": kp, "communities": comm, "engine": engine}
