"""Connected systems and data-recreation paths, in Neo4j with NetworkX as the always-on engine.

A *recreation path* is a chain of **active** links (a sync connector, a replication stream, a
restorable backup) that ends in a system the audit says must be clean. If such a path exists, a
record deleted at the end of it can be written again from its start, so cleaning the target alone
is not enough.

The topology is one graph definition (``dashboard/build_data.py`` writes it as node-link JSON and
the dashboard draws it). Here it is loaded into Neo4j when a server is configured and reachable,
and the same path queries run in NetworkX. When both engines are available they must agree: a
disagreement is reported, never hidden.

These paths are *topology-level risk context*. They are not findings: only evidence-backed
findings from the audit can appear in ``output.csv``.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx  # type: ignore[import-untyped]

from slam.config import Settings
from slam.contracts import CaseContext

MAX_HOPS = 3
Path_ = tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Link:
    source: str
    target: str
    kind: str  # "observed" (seen in the activity stream) or "inferred" (documented dependency)
    op: str
    active: bool
    restore: bool


@dataclass(frozen=True, slots=True)
class Topology:
    nodes: dict[str, dict[str, Any]]
    links: tuple[Link, ...]


def load_topology(path: Path) -> Topology:
    """Read the node-link graph that ``dashboard/build_data.py`` exported."""

    if not path.is_file():
        raise FileNotFoundError(f"{path} is missing; run python dashboard/build_data.py first")
    graph = json.loads(path.read_text(encoding="utf-8"))["graph"]
    nodes = {node["id"]: dict(node) for node in graph["nodes"]}
    links = tuple(
        Link(
            source=edge["source"],
            target=edge["target"],
            kind=str(edge.get("kind", "")),
            op=str(edge.get("op", "")),
            active=bool(edge.get("active")),
            restore=bool(edge.get("restore")),
        )
        for edge in graph["edges"]
    )
    return Topology(nodes=nodes, links=links)


def system_of(node: str) -> str:
    """``resource:SYSTEM:ID`` / ``system:SYSTEM`` -> ``SYSTEM`` (reconstruction's node naming)."""

    parts = node.split(":")
    return parts[1] if len(parts) > 1 else node


def evidenced_pairs(contexts: Iterable[CaseContext]) -> Counter[str]:
    """How many cases carry audit evidence of each active ``source>target`` system link."""

    counts: Counter[str] = Counter()
    for context in contexts:
        pairs = {
            f"{system_of(edge.source)}>{system_of(edge.target)}"
            for edge in (*context.active_flows, *context.restore_risks)
        }
        counts.update(pairs)
    return counts


class NetworkxGraph:
    engine = "networkx"

    def __init__(self, topology: Topology) -> None:
        self._graph = nx.DiGraph()
        self._graph.add_nodes_from(topology.nodes)
        for link in topology.links:
            if link.active:
                self._graph.add_edge(link.source, link.target)

    @property
    def version(self) -> str:
        return str(nx.__version__)

    def paths_into(self, target: str, max_hops: int = MAX_HOPS) -> list[Path_]:
        if target not in self._graph:
            return []
        found: list[Path_] = []
        for source in nx.ancestors(self._graph, target):
            found.extend(
                tuple(p) for p in nx.all_simple_paths(self._graph, source, target, cutoff=max_hops)
            )
        return sorted(found, key=lambda p: (len(p), p))

    def blast_radius(self, source: str) -> int:
        return len(nx.descendants(self._graph, source)) if source in self._graph else 0


class Neo4jGraph:
    engine = "neo4j"

    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._driver.verify_connectivity()

    def close(self) -> None:
        self._driver.close()

    @property
    def version(self) -> str:
        records, _, _ = self._driver.execute_query(
            "CALL dbms.components() YIELD name, versions RETURN name, versions[0] AS v"
        )
        return str(records[0]["v"]) if records else "unknown"

    def load(self, topology: Topology) -> None:
        """Replace the ``System`` graph with the topology (only our own label is touched)."""

        self._driver.execute_query("MATCH (n:System) DETACH DELETE n")
        self._driver.execute_query(
            "UNWIND $nodes AS n CREATE (:System {id: n.id, label: n.label, tier: n.tier})",
            nodes=[
                {"id": k, "label": str(v.get("label", k)), "tier": str(v.get("tier", ""))}
                for k, v in sorted(topology.nodes.items())
            ],
        )
        self._driver.execute_query(
            "UNWIND $links AS l MATCH (a:System {id: l.source}), (b:System {id: l.target}) "
            "CREATE (a)-[:LINKS {kind: l.kind, op: l.op, active: l.active, "
            "restore: l.restore}]->(b)",
            links=[
                {
                    "source": link.source,
                    "target": link.target,
                    "kind": link.kind,
                    "op": link.op,
                    "active": link.active,
                    "restore": link.restore,
                }
                for link in topology.links
            ],
        )

    def delete_systems(self, ids: Iterable[str]) -> int:
        """DETACH DELETE the systems and every link touching them; returns how many existed."""

        records, _, _ = self._driver.execute_query(
            "MATCH (n:System) WHERE n.id IN $ids DETACH DELETE n RETURN count(n) AS n",
            ids=sorted(set(ids)),
        )
        return int(records[0]["n"]) if records else 0

    def paths_into(self, target: str, max_hops: int = MAX_HOPS) -> list[Path_]:
        hops = int(max_hops)
        records, _, _ = self._driver.execute_query(
            f"MATCH p = (:System)-[:LINKS*1..{hops}]->(t:System {{id: $target}}) "
            "WHERE all(r IN relationships(p) WHERE r.active) "
            "RETURN [n IN nodes(p) | n.id] AS path",
            target=target,
        )
        paths = {tuple(record["path"]) for record in records}
        return sorted((p for p in paths if len(set(p)) == len(p)), key=lambda p: (len(p), p))

    def blast_radius(self, source: str) -> int:
        records, _, _ = self._driver.execute_query(
            "MATCH p = (:System {id: $source})-[:LINKS*1..10]->(d:System) "
            "WHERE all(r IN relationships(p) WHERE r.active) "
            "RETURN count(DISTINCT d) AS n",
            source=source,
        )
        return int(records[0]["n"]) if records else 0


@dataclass(slots=True)
class RecreationReport:
    engine: str
    engine_version: str
    neo4j: dict[str, Any]
    crosscheck: dict[str, Any] | None
    paths: dict[str, list[Path_]] = field(default_factory=dict)
    blast_radius: dict[str, int] = field(default_factory=dict)
    evidenced: dict[str, int] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    neo4j_deleted: int | None = None


def connect_neo4j(settings: Settings) -> tuple[Neo4jGraph | None, dict[str, Any]]:
    """Open the configured Neo4j server, or explain exactly why there is none."""

    if not settings.neo4j_uri or settings.neo4j_password is None:
        return None, {"configured": False, "reachable": False, "detail": "NEO4J_URI not set"}
    try:
        graph = Neo4jGraph(
            settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password.get_secret_value()
        )
    except Exception as exc:  # driver, auth and network errors are all "not usable"
        return None, {
            "configured": True,
            "reachable": False,
            "detail": f"{type(exc).__name__}: could not connect",
        }
    return graph, {"configured": True, "reachable": True, "detail": "connected"}


def without(topology: Topology, removed: frozenset[str]) -> Topology:
    """The topology after deleting systems: their nodes and every link touching them are gone."""

    return Topology(
        nodes={k: v for k, v in topology.nodes.items() if k not in removed},
        links=tuple(
            link
            for link in topology.links
            if link.source not in removed and link.target not in removed
        ),
    )


def analyse(
    topology: Topology,
    targets: Sequence[str],
    contexts: Iterable[CaseContext],
    settings: Settings,
    removed: frozenset[str] = frozenset(),
) -> RecreationReport:
    """Run every path query in NetworkX, and in Neo4j too when it is available.

    With ``removed`` the systems are deleted first: DETACH DELETE in Neo4j, node removal in
    NetworkX, and the queries run on what is left.
    """

    remaining = without(topology, removed)
    reference = NetworkxGraph(remaining)
    sources = sorted({link.source for link in remaining.links if link.active})
    paths = {target: reference.paths_into(target) for target in sorted(set(targets))}
    radius = {source: reference.blast_radius(source) for source in sources}
    report = RecreationReport(
        engine="networkx",
        engine_version=f"networkx {reference.version}",
        neo4j={},
        crosscheck=None,
        paths=paths,
        blast_radius=radius,
        evidenced=dict(sorted(evidenced_pairs(contexts).items())),
        removed=sorted(removed),
    )

    neo, report.neo4j = connect_neo4j(settings)
    if neo is None:
        return report
    try:
        neo.load(topology)
        if removed:
            report.neo4j_deleted = neo.delete_systems(removed)
        mismatches = [
            target for target in paths if neo.paths_into(target) != paths[target]
        ] + [f"radius:{s}" for s in sources if neo.blast_radius(s) != radius[s]]
        report.crosscheck = {
            "queries": len(paths) + len(sources),
            "agree": not mismatches,
            "mismatches": mismatches,
        }
        report.engine = "neo4j"
        report.engine_version = f"neo4j {neo.version} (driver) / networkx {reference.version}"
    finally:
        neo.close()
    return report
