from src.crawler.build_official_ontology_aliases import (
    CANONICAL_PATH, CORPUS_PATH, OUTPUT_PATH, build_aliases, load_corpus, load_json, normalize, serialize,
)


def current_aliases():
    return build_aliases(load_json(CANONICAL_PATH), load_corpus(CORPUS_PATH))


def test_aliases_are_official_source_variants_and_not_runtime_synonyms():
    output = current_aliases()

    assert output["alias_count"] > 0
    assert output["production_impact"] == "none"
    assert output["policies"]["heldout_testset_used"] is False
    assert output["policies"]["generated_user_phrases_allowed"] is False
    assert output["policies"]["contextual_labels_are_synonyms"] is False
    assert all(item["evidence_page_ids"] for item in output["aliases"])
    assert len({item["id"] for item in output["aliases"]}) == output["alias_count"]
    assert all(item["id"].startswith("alias:") for item in output["aliases"])


def test_exact_variants_normalize_to_canonical_and_contextual_labels_overlap():
    output = current_aliases()
    for item in output["aliases"]:
        alias, canonical = normalize(item["label"]), normalize(item["canonical_label"])
        if item["alias_type"] == "official_label_variant":
            assert alias == canonical
        else:
            assert alias in canonical or canonical in alias


def test_checked_in_aliases_are_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(current_aliases())
