"""Generate an Obsidian vault from the canonical ontology graph."""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

try:
    from .build_ontology_map import CORPUS_PATH, ROOT
except ImportError:  # direct script execution
    from build_ontology_map import CORPUS_PATH, ROOT


GRAPH_PATH = ROOT / "ontology" / "kdic-canonical-graph.json"
VAULT_PATH = ROOT / "ontology" / "obsidian"


NODE_TYPE_LABELS = {
    "Actor": "대상자·기관",
    "BusinessDomain": "업무영역",
    "Concept": "개념",
    "ContactPoint": "문의·접수처",
    "Document": "공식 문서",
    "EligibilityRule": "신청 조건",
    "Fact": "핵심 사실",
    "MonetaryRule": "금액 기준",
    "OfficialLabel": "공식 표기",
    "Procedure": "절차",
    "RequiredDocument": "구비서류",
    "Service": "서비스",
}

RELATION_LABELS = {
    "ASSERTS_ABOUT": "관련 사실",
    "BELONGS_TO_DOMAIN": "업무영역에 속함",
    "BELONGS_TO_SERVICE": "서비스에 속함",
    "DOCUMENTS_SERVICE": "서비스를 안내함",
    "EVIDENCE_FOR": "근거가 됨",
    "LABEL_FOR": "이 항목의 표기임",
}

REVIEW_STATUS_LABELS = {
    "base": "기본 업무 구조",
    "official_source": "공식 원문",
    "pending_domain_approval": "도메인 승인 대기",
    "source_verified_pending_domain_approval": "원문 검증 완료 · 도메인 승인 대기",
    "domain_approved": "도메인 승인 완료",
    "source_verified_domain_approved": "원문 검증·도메인 승인 완료",
    "domain_rejected": "도메인 검토 반려",
    "source_verified_domain_rejected": "원문 검증 완료 · 도메인 검토 반려",
    "domain_needs_changes": "도메인 수정 요청",
    "source_verified_domain_needs_changes": "원문 검증 완료 · 도메인 수정 요청",
}

ALIAS_TYPE_LABELS = {
    "official_label_variant": "공식 명칭의 표기 변형",
    "contextual_label": "문맥상 표기 (검색 동의어로 자동 사용하지 않음)",
}

def _safe_name(value: str) -> str:
    """Return a Windows-safe, Korean-preserving Obsidian note name."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", value)
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value or "이름 없음"


def _koreanize_display_text(value: str) -> str:
    """Replace remaining source-system abbreviations in visualization-only titles."""
    return value.replace("FAQ", "자주 묻는 질문").replace("TOP 10", "주요 10개")


def _document_label(node: dict, corpus: dict[str, dict]) -> str:
    source = corpus[node["page_id"]]
    business = _koreanize_display_text(source["business_function"])
    title = _koreanize_display_text(source.get("page_title") or "안내")
    return f"{business} · {title} · 공식 문서"


def _node_display_names(graph: dict, corpus: dict[str, dict]) -> dict[str, str]:
    """Create human-readable Korean titles used by Obsidian's graph view."""
    nodes = {node["id"]: node for node in graph["nodes"]}
    alias_targets = {edge["source"]: edge["target"] for edge in graph["edges"] if edge["relation"] == "LABEL_FOR"}
    names: dict[str, str] = {}
    for node in graph["nodes"]:
        node_type_label = NODE_TYPE_LABELS[node["node_type"]]
        if node["node_type"] == "Document":
            names[node["id"]] = _document_label(node, corpus)
        elif node["node_type"] == "Fact":
            names[node["id"]] = node["label"]
        elif node["node_type"] == "OfficialLabel":
            target = nodes[alias_targets[node["id"]]]
            names[node["id"]] = f"{_koreanize_display_text(node['label'])} · {_koreanize_display_text(target['label'])}의 표기"
        else:
            names[node["id"]] = f"{_koreanize_display_text(node['label'])} · {node_type_label}"

    duplicate_names = {name for name, count in Counter(names.values()).items() if count > 1}
    for node_id, name in list(names.items()):
        if name in duplicate_names:
            node_type_label = NODE_TYPE_LABELS[nodes[node_id]["node_type"]]
            names[node_id] = f"{name} · {node_type_label}"
    if len(set(names.values())) != len(names):
        raise ValueError("Korean Obsidian display names must be unique")
    return names


def _node_paths(graph: dict, corpus: dict[str, dict]) -> tuple[dict[str, str], dict[str, str]]:
    display_names = _node_display_names(graph, corpus)
    paths = {
        node["id"]: f"노드/{NODE_TYPE_LABELS[node['node_type']]}/{_safe_name(display_names[node['id']])}"
        for node in graph["nodes"]
    }
    return paths, display_names


def _link(path: str, label: str | None = None) -> str:
    return f"[[{path}{'|' + label if label else ''}]]"


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.rstrip() + "\n", encoding="utf-8", newline="\n")


def load_inputs() -> tuple[dict, dict[str, dict]]:
    graph = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
    with CORPUS_PATH.open(encoding="utf-8") as f:
        corpus = {row["page_id"]: row for line in f if (row := json.loads(line))}
    return graph, corpus


def build_vault(graph: dict, corpus: dict[str, dict], vault_path: Path = VAULT_PATH) -> dict:
    vault_path.mkdir(parents=True, exist_ok=True)
    # This directory contains generated Markdown only; remove stale notes from older graph versions.
    for path in vault_path.rglob("*.md"):
        path.unlink()

    nodes = {node["id"]: node for node in graph["nodes"]}
    node_paths, display_names = _node_paths(graph, corpus)
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for edge in graph["edges"]:
        outgoing[edge["source"]].append(edge)
        incoming[edge["target"]].append(edge)

    core_approval_complete = graph.get("approval", {}).get("core_approval_complete", False)
    aliases_pending = not graph.get("approval", {}).get("all_graph_review_items_complete", False)
    if core_approval_complete and aliases_pending:
        index_status = "정규 개념·핵심 사실 승인 완료 · 공식 표기 검토 대기 · 런타임 RAG 적용 차단"
    elif core_approval_complete:
        index_status = "모든 그래프 검토 항목 승인 완료 · 런타임 RAG 적용 차단"
    else:
        index_status = "도메인 검토 진행 중 · 런타임 RAG 적용 차단"
    index = [
        "# 예금보험공사 지식 관계 지도", "",
        "> `ontology/kdic-canonical-graph.json`에서 자동 생성된 시각화입니다. 생성된 노트는 직접 수정하지 않습니다.", "",
        f"- 노드: {graph['summary']['node_count']}개",
        f"- 연결: {graph['summary']['edge_count']}개",
        f"- 상태: {index_status}", "", "## 6대 업무영역", "",
    ]
    domains = [node for node in graph["nodes"] if node["node_type"] == "BusinessDomain"]
    for domain in domains:
        index.append(f"- {_link(node_paths[domain['id']], display_names[domain['id']])}")
    index += ["", "## 노드 유형", ""]
    for node_type, count in graph["summary"]["node_type_counts"].items():
        index.append(f"- {NODE_TYPE_LABELS[node_type]}: {count}개")
    index += ["", "## 보는 방법", "", "Obsidian의 그래프 뷰에서 업무영역을 중심으로 서비스, 공식 문서, 개념, 절차, 신청 조건, 핵심 사실의 연결을 탐색합니다. 핵심 사실만 보려면 `path:노드/핵심 사실` 필터를 사용합니다."]
    _write(vault_path / "00 Index.md", "\n".join(index))

    for node in graph["nodes"]:
        rows = [
            "---", f"노드_ID: {node['id']}", f"노드_유형: {NODE_TYPE_LABELS[node['node_type']]}",
            f"검토_상태: {REVIEW_STATUS_LABELS.get(node['status'], node['status'])}", "---", "", f"# {display_names[node['id']]}", "",
        ]
        if node["node_type"] == "Document":
            source = corpus[node["page_id"]]
            rows += [f"- 공식 원문: {source['source_url']}", f"- 원문 수집일: {source['collected_at']}", f"- 원문 해시: `{node['content_sha256']}`", "", "## 요약", "", source.get("summary", ""), ""]
        if node["node_type"] == "Fact":
            fact_note = (
                "- 이 항목은 공식 원문 확인과 도메인 담당자 승인을 마쳤습니다. 답변에는 현재 공식 원문을 다시 확인합니다."
                if node["status"] == "source_verified_domain_approved"
                else "- 이 항목은 공식 원문 확인을 마쳤지만, 도메인 담당자 승인은 아직 완료되지 않았습니다."
            )
            evidence = node["evidence"]
            rows += [
                fact_note,
                f"- 근거 페이지: `{evidence['page_id']}`",
                f"- 공식 원문: {evidence['source_url']}",
                f"- 원문 해시: `{evidence['content_sha256']}`",
                f"- 원문 인용: {evidence['quote']}",
                "",
            ]
        if node["node_type"] == "OfficialLabel":
            rows += [f"- 표기 구분: {ALIAS_TYPE_LABELS.get(node['alias_type'], node['alias_type'])}"]
            if node["alias_type"] == "contextual_label":
                rows += ["- 승인 의미: 공식 문맥에서 확인된 표기이며, 정규 명칭과 교환 가능한 검색 동의어는 아닙니다."]
            rows += [""]
        rows += ["## 이 항목에서 연결", ""]
        for edge in outgoing[node["id"]]:
            target = nodes[edge["target"]]
            rows.append(f"- {RELATION_LABELS.get(edge['relation'], edge['relation'])} → {_link(node_paths[target['id']], display_names[target['id']])}")
        if not outgoing[node["id"]]:
            rows.append("- 연결 없음")
        rows += ["", "## 이 항목으로 연결", ""]
        for edge in incoming[node["id"]]:
            source = nodes[edge["source"]]
            rows.append(f"- {_link(node_paths[source['id']], display_names[source['id']])} → {RELATION_LABELS.get(edge['relation'], edge['relation'])}")
        if not incoming[node["id"]]:
            rows.append("- 연결 없음")
        _write(vault_path / f"{node_paths[node['id']]}.md", "\n".join(rows))

    all_graph_approved = graph.get("approval", {}).get("all_graph_review_items_approved", False)
    review_state = (
        "정규 개념 45개, 핵심 사실 15개, 공식 표기 47개 모두 도메인 담당자 승인을 마쳤습니다. 문맥상 표기는 검색 동의어가 아닙니다."
        if all_graph_approved
        else "정규 개념 45개와 핵심 사실 15개는 승인됐지만 공식 표기 검토가 남아 있습니다."
        if core_approval_complete
        else "정규 개념과 핵심 사실은 도메인 담당자 승인을 기다리고 있습니다."
    )
    review = [
        "# 검토 상태", "",
        f"> {review_state}", "",
        "승인 결정의 정본은 `../review/canonical-ontology-decisions.json`입니다.",
        "이 볼트는 탐색용 시각화이며 승인 도구가 아닙니다.",
    ]
    _write(vault_path / "Review/Status.md", "\n".join(review))
    return {"nodes": len(nodes), "edges": len(graph["edges"]), "node_types": graph["summary"]["node_type_counts"]}


def main() -> int:
    graph, corpus = load_inputs()
    print("wrote Obsidian vault:", build_vault(graph, corpus))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
