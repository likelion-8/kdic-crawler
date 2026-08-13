from src.crawler.build_ontology_review_queue import (
    CORPUS_PATH,
    MAP_PATH,
    OUTPUT_PATH,
    build_queue,
    load_corpus,
    load_json,
)


def test_review_queue_covers_all_metadata_concepts_with_source_evidence():
    mapping = load_json(MAP_PATH)
    queue = build_queue(mapping, load_corpus(CORPUS_PATH))

    assert "Concepts: 95" in queue
    assert "Source documents: 58" in queue
    assert queue.count("- Review status: `proposed`") == len(mapping["concepts"])
    assert "`dp_protlmts`" in queue
    assert "content_sha256:" in queue
    assert "data/testset" in queue


def test_checked_in_review_queue_is_reproducible():
    assert OUTPUT_PATH.read_text(encoding="utf-8") == build_queue(
        load_json(MAP_PATH), load_corpus(CORPUS_PATH)
    )
