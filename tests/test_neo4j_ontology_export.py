import csv
import io

from src.crawler.build_neo4j_ontology_export import OUTPUT_DIR, build_export, load_inputs


def _rows(text: str):
    return list(csv.DictReader(io.StringIO(text)))


def test_export_covers_every_canonical_node_and_edge():
    graph = load_inputs()
    files = build_export(graph)
    node_rows = sum(len(_rows(content)) for name, content in files.items() if name.startswith("nodes-"))
    edge_rows = sum(len(_rows(content)) for name, content in files.items() if name.startswith("edges-"))

    assert node_rows == graph["summary"]["node_count"]
    assert edge_rows == graph["summary"]["edge_count"]
    assert len(_rows(files["nodes-fact.csv"])) == 15
    assert len(_rows(files["nodes-document.csv"])) == 58


def test_import_preserves_types_status_and_fact_evidence():
    files = build_export(load_inputs())
    cypher = files["import.cypher"]

    assert ":OntologyNode:Fact" in cypher
    assert "EVIDENCE_FOR" in cypher
    assert "n.status = row.status" in cypher
    assert (OUTPUT_DIR / "import.cypher").exists()
