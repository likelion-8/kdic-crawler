"""V5 zero-LLM request-unit contextual responsibility gate.

Design lineage:
- E30-B: separate published-content, external-execution, and responsibility semantics.
- E31: do not atomize actor/action/object/goal into detached spans.
- E37: classify independent request units and fuse CONTINUE/EXIT/MIXED.
- Fresh-v6 v4 failure analysis: remove arbitrary 60% tail slicing and single-axis veto.

V5 keeps each request unit's full context, uses BGE-m3-ko relational comparisons,
and exits only when external responsibility agrees with multiple independent semantic
axes. Unknown/conflicting cases fail open.

This module is intentionally self-contained:
- no generative model;
- no HTTP/API call;
- no retrieval/reranker;
- no E7/Supabase/database dependency;
- no arbitrary terminal-tail slicing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Sequence

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MODEL = "dragonkue/BGE-m3-ko"
FRAME_BANK_V2 = ROOT / "data" / "scope" / "gptlike_relational_frames_v2.json"

_REQUEST_UNIT_FRAMES = (
    "사용자가 독립적으로 답변을 요구하는 하나의 질문 또는 요청",
    "사용자가 별도의 정보, 판단 또는 행동 결과를 요구하는 독립 요청",
    "이 문장만 따로 두어도 사용자의 요구사항으로 답변할 수 있는 요청",
)
_CONTEXT_FRAMES = (
    "뒤의 요청을 이해하기 위한 배경 설명이나 상황 설명",
    "별도의 답변을 요구하지 않는 조건, 단서, 예시 또는 참고 문맥",
    "사용자의 실제 질문을 제한하거나 보충하는 설명이며 독립 요청은 아닌 문장",
)

# Domain-neutral surface boundaries only.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|[\r\n]+|[;；]+")
_COORDINATORS = (" 그리고 ", " 또한 ", " 또 ", " 그리고 나서 ", " 그다음 ")


@dataclass(frozen=True)
class Match:
    score: float
    frame_id: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AxisEvidence:
    kdic: Match
    external: Match
    external_margin: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "kdic": self.kdic.to_dict(),
            "external": self.external.to_dict(),
            "external_margin": self.external_margin,
        }


@dataclass(frozen=True)
class _EncodedGroup:
    kdic_ids: tuple[str, ...]
    kdic_texts: tuple[str, ...]
    kdic_embeddings: np.ndarray
    external_ids: tuple[str, ...]
    external_texts: tuple[str, ...]
    external_embeddings: np.ndarray


def _unit_rows(vectors: np.ndarray) -> np.ndarray:
    arr = np.asarray(vectors, dtype=np.float32)
    if arr.ndim != 2 or arr.shape[0] == 0:
        raise ValueError(f"expected non-empty 2-D embeddings, got {arr.shape}")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    if np.any(norms <= 1e-12):
        raise ValueError("zero-norm embedding")
    return arr / norms


class V5RelationalFrameBank:
    def __init__(
        self,
        path: Path = FRAME_BANK_V2,
        *,
        model_name: str = DEFAULT_MODEL,
        model,
    ) -> None:
        self.path = Path(path)
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        declared = str(payload.get("model") or "").strip()
        if declared and declared != model_name:
            raise ValueError(
                f"frame model={declared!r} does not match runtime={model_name!r}"
            )
        self.payload = payload
        self.model = model
        self.groups: dict[str, _EncodedGroup] = {}
        for axis in ("relation", "action", "terminal", "responsibility"):
            self.groups[axis] = self._encode_axis(axis)
        self.groups["contrast"] = self._encode_contrastive_pairs()

    def _encode_texts(self, texts: Sequence[str]) -> np.ndarray:
        return _unit_rows(np.asarray(
            self.model.encode(
                list(texts),
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=min(32, max(1, len(texts))),
            ),
            dtype=np.float32,
        ))

    def _encode_axis(self, axis: str) -> _EncodedGroup:
        raw = self.payload.get(axis) or {}
        kdic = list(raw.get("kdic") or [])
        external = list(raw.get("external") or [])
        if not kdic or not external:
            raise ValueError(f"axis {axis!r} must contain KDIC and external frames")
        k_ids = tuple(str(x["id"]) for x in kdic)
        k_texts = tuple(str(x["text"]) for x in kdic)
        e_ids = tuple(str(x["id"]) for x in external)
        e_texts = tuple(str(x["text"]) for x in external)
        return _EncodedGroup(
            kdic_ids=k_ids,
            kdic_texts=k_texts,
            kdic_embeddings=self._encode_texts(k_texts),
            external_ids=e_ids,
            external_texts=e_texts,
            external_embeddings=self._encode_texts(e_texts),
        )

    def _encode_contrastive_pairs(self) -> _EncodedGroup:
        pairs = list(self.payload.get("contrastive_pairs") or [])
        if not pairs:
            raise ValueError("contrastive_pairs must not be empty")
        ids = tuple(str(x["id"]) for x in pairs)
        k_texts = tuple(str(x["kdic"]) for x in pairs)
        e_texts = tuple(str(x["external"]) for x in pairs)
        return _EncodedGroup(
            kdic_ids=tuple(f"{x}:kdic" for x in ids),
            kdic_texts=k_texts,
            kdic_embeddings=self._encode_texts(k_texts),
            external_ids=tuple(f"{x}:external" for x in ids),
            external_texts=e_texts,
            external_embeddings=self._encode_texts(e_texts),
        )

    @staticmethod
    def _best(
        q: np.ndarray,
        ids: Sequence[str],
        texts: Sequence[str],
        emb: np.ndarray,
    ) -> Match:
        scores = emb @ q
        idx = int(np.argmax(scores))
        return Match(float(scores[idx]), str(ids[idx]), str(texts[idx]))

    def compare(self, axis: str, query_embedding: np.ndarray) -> AxisEvidence:
        group = self.groups[axis]
        q = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
        norm = float(np.linalg.norm(q))
        if norm <= 1e-12:
            raise ValueError("query embedding has zero norm")
        q = q / norm
        kdic = self._best(
            q, group.kdic_ids, group.kdic_texts, group.kdic_embeddings
        )
        external = self._best(
            q, group.external_ids, group.external_texts, group.external_embeddings
        )
        return AxisEvidence(
            kdic=kdic,
            external=external,
            external_margin=float(external.score - kdic.score),
        )


@dataclass(frozen=True)
class UnitEvidence:
    relation: AxisEvidence
    action: AxisEvidence
    terminal: AxisEvidence
    responsibility: AxisEvidence
    contrast: AxisEvidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "relation": self.relation.to_dict(),
            "action": self.action.to_dict(),
            "terminal": self.terminal.to_dict(),
            "responsibility": self.responsibility.to_dict(),
            "contrast": self.contrast.to_dict(),
        }


@dataclass(frozen=True)
class V5UnitDecision:
    request_unit: str
    prediction: str  # IN_SCOPE | OOS
    reason: str
    evidence: UnitEvidence | None = None
    external_support_axes: tuple[str, ...] = ()
    request_margin: float | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.evidence is not None:
            payload["evidence"] = self.evidence.to_dict()
        return payload


@dataclass(frozen=True)
class V5QueryDecision:
    action: str  # CONTINUE | EXIT | MIXED
    prediction: str  # IN_SCOPE | OOS | MIXED
    units: tuple[V5UnitDecision, ...]
    unitizer_mode: str

    @property
    def in_scope_units(self) -> tuple[V5UnitDecision, ...]:
        return tuple(x for x in self.units if x.prediction == "IN_SCOPE")

    @property
    def oos_units(self) -> tuple[V5UnitDecision, ...]:
        return tuple(x for x in self.units if x.prediction == "OOS")

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "prediction": self.prediction,
            "unitizer_mode": self.unitizer_mode,
            "units": [x.to_dict() for x in self.units],
            "in_scope_count": len(self.in_scope_units),
            "oos_count": len(self.oos_units),
        }


class V5RequestUnitizer:
    """Conservative semantic request-unit decomposition.

    Split only when two or more surface segments independently look more like
    requests than background. Otherwise preserve the exact full request context.
    """

    def __init__(self, model) -> None:
        self.model = model
        self.request_embeddings = self._encode(_REQUEST_UNIT_FRAMES)
        self.context_embeddings = self._encode(_CONTEXT_FRAMES)

    def _encode(self, texts: Sequence[str]) -> np.ndarray:
        return _unit_rows(np.asarray(
            self.model.encode(
                list(texts),
                normalize_embeddings=True,
                show_progress_bar=False,
                batch_size=min(32, max(1, len(texts))),
            ),
            dtype=np.float32,
        ))

    def request_margin(self, text: str) -> float:
        text = " ".join(str(text or "").strip().split())
        if not text:
            return -1.0
        q = self._encode([text])[0]
        return float(
            np.max(self.request_embeddings @ q)
            - np.max(self.context_embeddings @ q)
        )

    @staticmethod
    def _surface_segments(text: str) -> list[str]:
        parts = [
            " ".join(x.strip().split())
            for x in _SENTENCE_BOUNDARY.split(text)
            if x.strip()
        ]
        return parts or ([text] if text else [])

    def _coordinator_split(self, text: str) -> list[str] | None:
        for marker in _COORDINATORS:
            if marker not in text:
                continue
            left, right = text.split(marker, 1)
            left, right = left.strip(), right.strip()
            if len(left) < 4 or len(right) < 4:
                continue
            if self.request_margin(left) > 0.0 and self.request_margin(right) > 0.0:
                return [left, right]
        return None

    def split(self, query: str) -> tuple[tuple[str, ...], str]:
        full = " ".join(str(query or "").strip().split())
        if not full:
            return (), "empty"

        segments = self._surface_segments(full)
        if len(segments) == 1:
            inline = self._coordinator_split(full)
            if inline is None:
                return (full,), "single_full_context"
            segments = inline
            mode = "semantic_coordinator_split"
        else:
            mode = "semantic_sentence_split"

        margins = [self.request_margin(x) for x in segments]
        if sum(m > 0.0 for m in margins) < 2:
            return (full,), "split_rejected_preserve_full_context"

        units: list[str] = []
        buffer: list[str] = []
        for i, segment in enumerate(segments):
            if margins[i] <= 0.0:
                buffer.append(segment)
                continue
            unit = " ".join(buffer + [segment]).strip()
            buffer.clear()
            if unit:
                units.append(unit)

        if buffer:
            if units:
                units[-1] = " ".join([units[-1], *buffer]).strip()
            else:
                return (full,), "split_rejected_preserve_full_context"

        if len(units) < 2:
            return (full,), "split_rejected_preserve_full_context"
        return tuple(units), mode


class V5NonLLMScopeGate:
    """Per-request-unit full-context BGE responsibility classifier."""

    def __init__(
        self,
        *,
        model_name: str = DEFAULT_MODEL,
        device: str | None = None,
        model=None,
        frames: V5RelationalFrameBank | None = None,
    ) -> None:
        self.model_name = model_name
        if model is None:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(model_name, device=device)
        self.model = model
        self.frames = frames or V5RelationalFrameBank(
            FRAME_BANK_V2, model_name=model_name, model=self.model
        )
        self.unitizer = V5RequestUnitizer(self.model)

    def _embed(self, text: str) -> np.ndarray:
        return np.asarray(
            self.model.encode(
                [text],
                normalize_embeddings=True,
                show_progress_bar=False,
            )[0],
            dtype=np.float32,
        )

    def _evidence(self, text: str) -> UnitEvidence:
        q = self._embed(text)
        return UnitEvidence(
            relation=self.frames.compare("relation", q),
            action=self.frames.compare("action", q),
            terminal=self.frames.compare("terminal", q),
            responsibility=self.frames.compare("responsibility", q),
            contrast=self.frames.compare("contrast", q),
        )

    @staticmethod
    def _decide(e: UnitEvidence) -> tuple[str, str, tuple[str, ...]]:
        margins = {
            "relation": float(e.relation.external_margin),
            "action": float(e.action.external_margin),
            "terminal": float(e.terminal.external_margin),
            "responsibility": float(e.responsibility.external_margin),
            "contrast": float(e.contrast.external_margin),
        }
        support = tuple(
            axis
            for axis in ("relation", "action", "terminal", "responsibility", "contrast")
            if margins[axis] > 0.0
        )

        # V5 structural rescue after consumed DEV replay:
        # responsibility evidence has two independent semantic forms.
        # 1) The explicit responsibility axis must agree with requested action/outcome.
        # 2) A contrastive pair is already a joint actor/action/outcome relation; when
        #    external it can establish responsibility if one independent core axis
        #    (relation/action/terminal) also agrees. Neither route permits a single
        #    axis veto, and no numeric threshold is introduced or tuned.
        explicit_responsibility = (
            margins["responsibility"] > 0.0
            and (margins["action"] > 0.0 or margins["terminal"] > 0.0)
        )
        contrastive_responsibility = (
            margins["contrast"] > 0.0
            and (
                margins["relation"] > 0.0
                or margins["action"] > 0.0
                or margins["terminal"] > 0.0
            )
        )
        external_coherent = explicit_responsibility or contrastive_responsibility
        if external_coherent:
            route = (
                "explicit_responsibility_agreement"
                if explicit_responsibility
                else "contrastive_responsibility_agreement"
            )
            return "OOS", route, support

        return "IN_SCOPE", "insufficient_external_responsibility_agreement_fail_open", support

    def classify_unit(self, request_unit: str) -> V5UnitDecision:
        unit = " ".join(str(request_unit or "").strip().split())
        if not unit:
            return V5UnitDecision(
                request_unit="",
                prediction="IN_SCOPE",
                reason="empty_unit_fail_open",
            )
        try:
            evidence = self._evidence(unit)
            prediction, reason, support = self._decide(evidence)
            return V5UnitDecision(
                request_unit=unit,
                prediction=prediction,
                reason=reason,
                evidence=evidence,
                external_support_axes=support,
                request_margin=self.unitizer.request_margin(unit),
            )
        except Exception as exc:
            return V5UnitDecision(
                request_unit=unit,
                prediction="IN_SCOPE",
                reason="runtime_error_fail_open",
                error=f"{type(exc).__name__}: {exc}",
            )

    def classify(self, query: str) -> V5QueryDecision:
        full = " ".join(str(query or "").strip().split())
        if not full:
            return V5QueryDecision(
                action="CONTINUE",
                prediction="IN_SCOPE",
                units=(),
                unitizer_mode="empty",
            )
        try:
            unit_texts, mode = self.unitizer.split(full)
        except Exception:
            unit_texts, mode = (full,), "unitizer_error_preserve_full_context"

        units = tuple(self.classify_unit(x) for x in unit_texts)
        labels = {x.prediction for x in units}
        if labels == {"OOS"}:
            action, prediction = "EXIT", "OOS"
        elif labels == {"IN_SCOPE"} or not labels:
            action, prediction = "CONTINUE", "IN_SCOPE"
        else:
            action, prediction = "MIXED", "MIXED"
        return V5QueryDecision(
            action=action,
            prediction=prediction,
            units=units,
            unitizer_mode=mode,
        )


class GPUV5ScopeGate(V5NonLLMScopeGate):
    def __init__(self, *, model_name: str = DEFAULT_MODEL) -> None:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for GPUV5ScopeGate")
        super().__init__(model_name=model_name, device="cuda")

    @property
    def cuda_device_name(self) -> str:
        import torch
        return torch.cuda.get_device_name(0)


_gate_cache: dict[str, V5NonLLMScopeGate] = {}


def classify_gptlike_scope_v5(query: str) -> V5QueryDecision:
    if "default" not in _gate_cache:
        _gate_cache["default"] = V5NonLLMScopeGate()
    return _gate_cache["default"].classify(query)
