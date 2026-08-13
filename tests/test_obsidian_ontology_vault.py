from src.crawler.build_obsidian_ontology_vault import (
    GRAPH_PATH,
    VAULT_PATH,
    _node_display_names,
    _node_paths,
    build_vault,
    load_inputs,
)


def test_vault_has_one_note_per_canonical_graph_node():
    graph, corpus = load_inputs()
    stats = build_vault(graph, corpus, VAULT_PATH)

    assert stats["nodes"] == graph["summary"]["node_count"]
    assert stats["edges"] == graph["summary"]["edge_count"]
    assert (VAULT_PATH / "00 Index.md").exists()
    assert len(list((VAULT_PATH / "노드").rglob("*.md"))) == graph["summary"]["node_count"]
    assert len(list((VAULT_PATH / "노드" / "핵심 사실").glob("*.md"))) == 15
    assert GRAPH_PATH.exists()


def test_korean_node_and_relation_names_are_used_for_graph_visualization():
    graph, corpus = load_inputs()
    build_vault(graph, corpus, VAULT_PATH)
    paths, names = _node_paths(graph, corpus)
    document = (VAULT_PATH / f"{paths['document:dp_protlmts']}.md").read_text(encoding="utf-8")
    fact = (VAULT_PATH / f"{paths['fact:deposit_protection_limit']}.md").read_text(encoding="utf-8")

    assert names["document:dp_protlmts"] == "예금자보호제도 · 보호한도 · 공식 문서"
    assert names["fact:deposit_protection_limit"] == "예금자 보호한도 1인·금융회사별 1억원"
    assert "근거가 됨" in document
    assert "예금자 보호한도 1인·금융회사별 1억원" in fact
    assert "원문 검증·도메인 승인 완료" in fact


def test_six_business_domains_are_linked_from_korean_index():
    graph, corpus = load_inputs()
    build_vault(graph, corpus, VAULT_PATH)
    index = (VAULT_PATH / "00 Index.md").read_text(encoding="utf-8")
    display_names = _node_display_names(graph, corpus)

    domains = [node for node in graph["nodes"] if node["node_type"] == "BusinessDomain"]
    assert len(domains) == 6
    assert "## 6대 업무영역" in index
    assert all(display_names[domain["id"]] in index for domain in domains)
