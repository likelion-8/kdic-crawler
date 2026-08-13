from copy import deepcopy

from src.eval.validate_ontology_schema_alignment import (
    current_validation,
    load_corpus,
    load_json,
    load_schema,
    GRAPH_PATH,
    validate,
)


def test_current_canonical_graph_matches_the_declared_ontology_schema():
    output = current_validation()

    assert output["valid"] is True
    assert output["declared_class_count"] == 12
    assert output["declared_relation_count"] == 6
    assert output["errors"] == []


def test_validator_rejects_an_undeclared_graph_node_type():
    graph = deepcopy(load_json(GRAPH_PATH))
    graph["nodes"][0]["node_type"] = "UnknownType"

    output = validate(load_schema(), graph, load_corpus())

    assert output["valid"] is False
    assert any("undeclared graph node types: UnknownType" in error for error in output["errors"])
