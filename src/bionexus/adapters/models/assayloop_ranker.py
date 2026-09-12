"""AssayLoop bridge — their policy, our loop.

Genentech's AssayLoop (MIT) contributes trained acquisition policies for
screen-style problems (AssayFormer: LLM warm start -> amortized ranker over
gene libraries). BioNexus contributes the execution and trust layer: gates,
instruments, provenance, evals. This adapter plugs an assaybench-style
policy into a BioNexus campaign without either repo depending on the other.

The policy contract (duck-typed, mirrors assaybench.Model):
    predict(observations, candidates, task_context=None) -> obj.scores: dict

    observations: iterable of records with .candidate and .label
    (label: {"hit": bool, "relevance_score": float})

Use `policy=` with any local object satisfying that contract (tests, your own
model). With no policy, attempts to load Genentech's released checkpoint —
requires `pip install assayloop torch huggingface-hub`.
"""
from __future__ import annotations

from typing import Any


class _Obs:
    __slots__ = ("candidate", "label")

    def __init__(self, candidate: str, label: dict):
        self.candidate = candidate
        self.label = label


class AssayLoopRanker:
    name = "assayloop-ranker"

    def __init__(self, policy: Any | None = None, checkpoint: str | None = None):
        if policy is None:
            policy = self._load_released(checkpoint)
        self.policy = policy

    @staticmethod
    def _load_released(checkpoint: str | None):
        try:
            from huggingface_hub import snapshot_download
            from assayloop.models.amortized_ranker import AmortizedRankerModel
        except ImportError as exc:
            raise ImportError(
                "no policy given and assayloop is not installed: "
                "pass policy=<assaybench-style Model> or "
                "pip install assayloop torch huggingface-hub") from exc
        ckpt = checkpoint or snapshot_download("Genentech/assayformer")
        return AmortizedRankerModel(checkpoint=ckpt, ckpt_file="model_last.pt")

    def rank(self, candidates: list[str],
             observations: list[dict] | None = None) -> list[tuple[str, float]]:
        """observations: [{candidate, hit, relevance_score}, ...]"""
        obs = [_Obs(o["candidate"],
                    {"hit": bool(o.get("hit", False)),
                     "relevance_score": float(o.get("relevance_score", 0.0))})
               for o in (observations or [])]
        pred = self.policy.predict(obs, list(candidates))
        scores = getattr(pred, "scores", pred)
        return sorted(((c, float(scores.get(c, 0.0))) for c in candidates),
                      key=lambda t: -t[1])

    def pick_batch(self, candidates: list[str], observations: list[dict] | None,
                   n: int) -> list[str]:
        return [c for c, _ in self.rank(candidates, observations)[:n]]
