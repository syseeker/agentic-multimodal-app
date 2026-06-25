"""cuGraph→NetworkX fallback compute (no GPU, no DB needed)."""
from app.graph.analytics import _networkx


def test_networkx_key_players_and_communities():
    edges = [
        ("person:mei", "person:john"),
        ("person:ah-kow", "person:john"),
        ("person:rajesh", "person:john"),
        ("person:samad", "person:ah-kow"),
    ]
    key_players, communities, engine = _networkx(edges)
    assert engine == "networkx"
    # John is the hub -> should top centrality.
    assert key_players[0]["id"] == "person:john"
    assert len(communities) >= 1


def test_networkx_empty():
    assert _networkx([]) == ([], [], "networkx")
