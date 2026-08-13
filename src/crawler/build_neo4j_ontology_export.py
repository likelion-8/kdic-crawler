"""Export the canonical ontology graph as Neo4j CSV/Cypher without starting Neo4j."""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
from collections import defaultdict
from pathlib import Path

try:
    from .build_ontology_map import ROOT
except ImportError:
    from build_ontology_map import ROOT


GRAPH_PATH = ROOT / "ontology" / "kdic-canonical-graph.json"
OUTPUT_DIR = ROOT / "ontology" / "neo4j"


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_").lower()


def _csv(rows: list[dict], fields: list[str]) -> str:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue()


def load_inputs() -> dict:
    return json.loads(GRAPH_PATH.read_text(encoding="utf-8"))


def build_export(graph: dict) -> dict[str, str]:
    node_groups = defaultdict(list)
    edge_groups = defaultdict(list)
    for node in graph["nodes"]:
        extras = {key: value for key, value in node.items() if key not in {"id", "node_type", "label", "status"}}
        node_groups[node["node_type"]].append({
            "id": node["id"], "label": node["label"], "status": node["status"],
            "properties_json": json.dumps(extras, ensure_ascii=False, separators=(",", ":")),
        })
    for edge in graph["edges"]:
        edge_groups[edge["relation"]].append({
            "start_id": edge["source"], "end_id": edge["target"],
            "evidence_page_id": edge.get("evidence_page_id", ""),
        })

    files = {}
    cypher = [
        "// Generated canonical ontology import. Copy CSV files into Neo4j's import directory.",
        "CREATE CONSTRAINT ontology_node_id IF NOT EXISTS FOR (n:OntologyNode) REQUIRE n.id IS UNIQUE;", "",
    ]
    for node_type in sorted(node_groups):
        name = f"nodes-{_safe(node_type)}.csv"
        files[name] = _csv(node_groups[node_type], ["id", "label", "status", "properties_json"])
        cypher += [
            f"LOAD CSV WITH HEADERS FROM 'file:///{name}' AS row",
            f"MERGE (n:OntologyNode:{node_type} {{id: row.id}})",
            f"SET n.label = row.label, n.status = row.status, n.node_type = '{node_type}', n.properties_json = row.properties_json;", "",
        ]
    for relation in sorted(edge_groups):
        name = f"edges-{_safe(relation)}.csv"
        files[name] = _csv(edge_groups[relation], ["start_id", "end_id", "evidence_page_id"])
        cypher += [
            f"LOAD CSV WITH HEADERS FROM 'file:///{name}' AS row",
            "MATCH (a:OntologyNode {id: row.start_id}), (b:OntologyNode {id: row.end_id})",
            f"MERGE (a)-[r:{relation}]->(b)",
            "SET r.evidence_page_id = CASE WHEN row.evidence_page_id = '' THEN null ELSE row.evidence_page_id END;", "",
        ]
    files["import.cypher"] = "\n".join(cypher).rstrip() + "\n"
    files["README.md"] = f"""# Neo4j canonical ontology export

Generated from `ontology/kdic-canonical-graph.json`: {graph['summary']['node_count']} nodes and {graph['summary']['edge_count']} relationships.

No Neo4j server is installed or started by this generator. Copy all CSV files to Neo4j's configured import directory, then run `import.cypher`. Nodes preserve their review status. Canonical entities, core facts, and official labels are approved, but contextual labels remain non-synonyms and no node is automatically enabled in production.
"""
    return files


def write_export(files: dict[str, str], output_dir: Path = OUTPUT_DIR) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in output_dir.iterdir():
        if path.is_file() and path.name not in files:
            path.unlink()
    for name, content in files.items():
        (output_dir / name).write_text(content, encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    graph = load_inputs()
    files = build_export(graph)
    if args.check:
        existing = {path.name for path in OUTPUT_DIR.iterdir() if path.is_file()} if OUTPUT_DIR.exists() else set()
        stale = [name for name, content in files.items() if name not in existing or (OUTPUT_DIR / name).read_text(encoding="utf-8") != content]
        extra = sorted(existing - set(files))
        if stale or extra:
            raise SystemExit("Neo4j export is stale: " + ", ".join(stale + extra))
        print("Neo4j canonical export is current")
        return 0
    write_export(files)
    print(f"wrote Neo4j canonical export: {graph['summary']['node_count']} nodes, {graph['summary']['edge_count']} edges")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
