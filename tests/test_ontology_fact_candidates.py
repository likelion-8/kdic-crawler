from src.crawler.build_ontology_fact_candidates import (
    OUTPUT_PATH,
    build_candidates,
    load_corpus,
    serialize,
)
from src.crawler.build_ontology_map import CORPUS_PATH


def test_fact_candidates_are_literal_and_source_grounded():
    payload = build_candidates(load_corpus(CORPUS_PATH))

    assert payload["source"]["document_count"] == 58
    assert payload["candidate_count"] == len(payload["candidates"]) > 0
    assert all(c["status"] == "proposed" for c in payload["candidates"])
    assert all(c["review_status"] == "unreviewed" for c in payload["candidates"])
    assert all(c["evidence"]["page_id"] and c["evidence"]["content_sha256"]
               for c in payload["candidates"])


def test_protection_limit_candidate_contains_one_hundred_million_won_evidence():
    payload = build_candidates(load_corpus(CORPUS_PATH))
    matches = [c for c in payload["candidates"]
               if c["evidence"]["page_id"] == "dp_protlmts"
               and c["object"]["value"] == "1억원"]

    assert matches
    assert any(c["object"]["candidate_type"] == "monetary" for c in matches)


def test_checked_in_candidates_are_reproducible():
    payload = build_candidates(load_corpus(CORPUS_PATH))
    assert OUTPUT_PATH.read_text(encoding="utf-8") == serialize(payload)
