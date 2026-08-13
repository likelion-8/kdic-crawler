from src.crawler.build_ontology_domain_review_packets import (
    CANONICAL_PATH,
    DECISIONS_PATH,
    FACT_GAP_DECISIONS_PATH,
    FACT_GAP_PATH,
    FACTS_PATH,
    MAP_PATH,
    OUTPUT_DIR,
    build_packets,
    load_json,
)


def current_packets():
    return build_packets(
        load_json(MAP_PATH), load_json(CANONICAL_PATH), load_json(FACTS_PATH),
        load_json(DECISIONS_PATH), load_json(FACT_GAP_PATH), load_json(FACT_GAP_DECISIONS_PATH),
    )


def test_domain_review_packets_split_all_decisions_across_six_business_domains():
    packets = current_packets()
    index = packets["INDEX.md"]

    assert set(packets) == {
        "INDEX.md", "concealed_assets_report.md", "debt_adjustment.md",
        "deposit_insurance_payment.md", "deposit_protection.md",
        "mistaken_remittance_return.md", "unclaimed_funds.md",
    }
    assert "| 예금보험금 안내 | 4 | 4 | 0 | 3 |" in index
    assert "| 고객 미수령금 신청 | 10 | 10 | 0 | 3 |" in index
    assert sum(packet.count("## Canonical 엔터티") for name, packet in packets.items() if name != "INDEX.md") == 6
    assert sum(packet.count("### `") for name, packet in packets.items() if name != "INDEX.md") == 66
    assert sum(packet.count("- 현재 결정: `approved` (hjy10 · 2026-08-12)") for name, packet in packets.items() if name != "INDEX.md") == 66


def test_checked_in_domain_review_packets_are_reproducible():
    for name, content in current_packets().items():
        assert (OUTPUT_DIR / name).read_text(encoding="utf-8") == content
