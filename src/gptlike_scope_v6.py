"""V6 unitizer-only rescue over frozen V5 semantic classifier.

V6 intentionally changes only request-unit decomposition. The V5 relational
classifier, frame bank, thresholds, and OOS decision rule remain untouched.

Design:
- create candidate boundaries from strong discourse structure;
- preserve each resulting unit as full text;
- never split actor/action/object spans internally;
- classify each unit with the frozen V5 semantic classifier;
- fuse all-IN -> CONTINUE, all-OOS -> EXIT, mixed -> MIXED.

No LLM, HTTP/API, retrieval, post-ranking, or database dependency.
"""
from __future__ import annotations

import re

from gptlike_scope_v5 import DEFAULT_MODEL, V5NonLLMScopeGate, V5QueryDecision

# Strong sentence-level boundaries. These are domain-neutral discourse signals,
# not KDIC/OOS topic keywords.
_SENTENCE_BOUNDARY = re.compile(r"(?<=[.!?。！？])\s+|[\r\n]+|[;；]+")
_ADDON_BOUNDARY = re.compile(
    r"\s+(?=(?:별도로|별개로|추가로|추가적으로|그리고|또한|또\s+다른|아울러|한편|동시에)\s+)"
)

# Language-form request closure only. It does not encode scope/topic. Korean
# request endings are intentionally broad because V5 Fresh-v7 showed that BGE
# meta-request margins reject genuine requests such as "작성해 주세요".
_REQUEST_CLOSURE = re.compile(
    r"(?:"
    r"[?？][.!。！？]?$|"
    r"(?:주세요|줘|줘요|해줘|해줘요|해\s*주세요|부탁해|부탁드립니다|바랍니다)[.!。！？]?$|"
    r"(?:인가요|되나요|하나요|있나요|맞나요|가능한가요)[?？.!。！？]?$"
    r")",
    re.IGNORECASE,
)


class V6DiscourseRequestUnitizer:
    """Conservative discourse-aware independent-request splitter.

    The failed V5 unitizer required a BGE meta-classification margin > 0 for
    every segment. Fresh-v7 showed genuine independent requests often fall
    below that meta boundary. V6 therefore removes only that veto.

    Strong discourse boundaries propose candidates; both sides must end as
    independently answerable requests. Otherwise the exact full query is kept.
    """

    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(str(text or "").strip().split())

    @classmethod
    def _request_like(cls, text: str) -> bool:
        x = cls._clean(text)
        if len(x) < 4:
            return False
        return bool(_REQUEST_CLOSURE.search(x))

    @classmethod
    def _candidate_segments(cls, full: str) -> tuple[list[str], str]:
        sentence = [cls._clean(x) for x in _SENTENCE_BOUNDARY.split(full) if cls._clean(x)]
        if len(sentence) >= 2:
            return sentence, "discourse_sentence_boundary"

        inline = [cls._clean(x) for x in _ADDON_BOUNDARY.split(full) if cls._clean(x)]
        if len(inline) >= 2:
            return inline, "discourse_additive_boundary"

        return [full], "single_full_context"

    def split(self, query: str) -> tuple[tuple[str, ...], str]:
        full = self._clean(query)
        if not full:
            return (), "empty"

        segments, mode = self._candidate_segments(full)
        if len(segments) < 2:
            return (full,), mode

        # Attach non-request background/context to the next actual request.
        # Never atomize the content of a request itself.
        units: list[str] = []
        buffer: list[str] = []
        for segment in segments:
            if self._request_like(segment):
                unit = self._clean(" ".join([*buffer, segment]))
                buffer.clear()
                if unit:
                    units.append(unit)
            else:
                buffer.append(segment)

        if buffer:
            if units:
                units[-1] = self._clean(" ".join([units[-1], *buffer]))
            else:
                return (full,), "split_rejected_preserve_full_context"

        if len(units) < 2:
            return (full,), "split_rejected_preserve_full_context"
        return tuple(units), mode

    # Schema compatibility only; it is not used as a split threshold in V6.
    @staticmethod
    def request_margin(text: str) -> float:
        return 1.0 if V6DiscourseRequestUnitizer._request_like(text) else -1.0


class V6NonLLMScopeGate(V5NonLLMScopeGate):
    """Frozen V5 semantic classifier + V6 unitizer-only change."""

    def __init__(self, *, model_name: str = DEFAULT_MODEL, device: str | None = None, model=None, frames=None) -> None:
        super().__init__(model_name=model_name, device=device, model=model, frames=frames)
        self.unitizer = V6DiscourseRequestUnitizer()


class GPUV6ScopeGate(V6NonLLMScopeGate):
    def __init__(self, *, model_name: str = DEFAULT_MODEL) -> None:
        import torch
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for GPUV6ScopeGate")
        super().__init__(model_name=model_name, device="cuda")

    @property
    def cuda_device_name(self) -> str:
        import torch
        return torch.cuda.get_device_name(0)


_gate_cache: dict[str, V6NonLLMScopeGate] = {}


def classify_gptlike_scope_v6(query: str) -> V5QueryDecision:
    if "default" not in _gate_cache:
        _gate_cache["default"] = V6NonLLMScopeGate()
    return _gate_cache["default"].classify(query)
