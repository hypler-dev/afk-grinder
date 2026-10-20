"""Offline state evidence inspection over validated packs.

This module only combines caller-supplied anchor scores with immutable
observation metadata.  It does not inspect pixels, load an SDK, capture a
window, operate input, or authorize any action.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

from afk_grinder.recognition.observation import Layout, Observation
from afk_grinder.recognition.packs import ResourcePack, SUPPORTED_STATE_KINDS, State


@dataclass(frozen=True, slots=True)
class StateInspection:
    """One fail-closed interpretation of a single observation.

    ``state_id`` is present only for a temporally stable, unique candidate.
    ``kind`` is present only with that stable identity.  A stable ``unknown``
    kind is a unique supported unknown-screen class; it never permits action.
    ``stable_frames`` may show progress for an otherwise unknown result.
    """

    status: str
    state_id: str | None
    reason: str
    stable_frames: int
    kind: str | None = None


class StateInspector:
    """Interpret validated-pack scores without retaining observations or pixels."""

    def __init__(self, pack: ResourcePack):
        if type(pack) is not ResourcePack:
            raise TypeError("StateInspector requires a validated ResourcePack.")
        self._states = pack.states
        self._thresholds = {anchor.id: anchor.threshold for anchor in pack.anchors}
        self._watermark: tuple[int, int, float] | None = None
        self._last_layout: Layout | None = None
        self._last_candidate: str | None = None
        self._last_generation: int | None = None
        self._last_sequence: int | None = None
        self._stable_frames = 0

    def inspect(self, observation: Observation, scores: dict[str, int | float | None], *, now: int | float) -> StateInspection:
        """Return only supported, fresh, ordered and stable pack-state evidence."""
        if type(observation) is not Observation:
            return self._unknown("invalid_observation")
        if not _finite_number(now):
            return self._unknown("invalid_time")
        if observation.layout.region_kind != "client" or not observation.layout.content_verified:
            return self._unknown("unverified_layout")
        if observation.captured_at > now:
            return self._unknown("future")
        if now - observation.captured_at > 0.5:
            return self._unknown("stale")
        if self._out_of_order(observation):
            return self._unknown("out_of_order")

        # The identity is consumed before evidence validation.  A bad score
        # payload cannot be retried later as a fresh observation.
        self._watermark = (observation.generation, observation.sequence, observation.captured_at)
        if not self._valid_scores(scores):
            return self._unknown("invalid_evidence")

        blocked = False
        candidates: list[State] = []
        unresolved = False
        for state in self._states:
            positive = tuple(scores.get(anchor_id) for anchor_id in state.positive)
            if any(score is not None and not self._matches(anchor_id, score)
                   for anchor_id, score in zip(state.positive, positive)):
                continue
            if any(score is None for score in positive):
                unresolved = True
                continue

            exclusions = tuple(scores.get(anchor_id) for anchor_id in state.exclude)
            if any(score is not None and self._matches(anchor_id, score)
                   for anchor_id, score in zip(state.exclude, exclusions)):
                blocked = True
                continue
            if any(score is None for score in exclusions):
                unresolved = True
                continue
            candidates.append(state)

        if blocked:
            return self._blocked()
        if len(candidates) != 1:
            if candidates:
                return self._unknown("ambiguous")
            return self._unknown("insufficient_evidence" if unresolved else "no_match")
        if unresolved:
            return self._unknown("insufficient_evidence")

        return self._candidate(candidates[0], observation)

    def _out_of_order(self, observation: Observation) -> bool:
        if self._watermark is None:
            return False
        generation, sequence, captured_at = self._watermark
        return (observation.generation < generation
                or observation.sequence <= sequence
                or observation.captured_at <= captured_at)

    def _valid_scores(self, scores: object) -> bool:
        if type(scores) is not dict or any(anchor_id not in self._thresholds for anchor_id in scores):
            return False
        return all(score is None or _score_number(score) for score in scores.values())

    def _matches(self, anchor_id: str, score: int | float) -> bool:
        return score >= self._thresholds[anchor_id]

    def _candidate(self, state: State, observation: Observation) -> StateInspection:
        if type(state.kind) is not str or state.kind not in SUPPORTED_STATE_KINDS:
            return self._unknown("invalid_state_kind")
        consecutive = (self._last_candidate == state.id
                       and self._last_layout == observation.layout
                       and self._last_generation == observation.generation
                       and self._last_sequence is not None
                       and observation.sequence == self._last_sequence + 1)
        self._stable_frames = min(self._stable_frames + 1, state.stable_frames) if consecutive else 1
        self._last_candidate = state.id
        self._last_layout = observation.layout
        self._last_generation = observation.generation
        self._last_sequence = observation.sequence
        if self._stable_frames >= state.stable_frames:
            if state.kind in {"unclassified", "gameplay"}:
                return StateInspection("known", state.id, "stable", self._stable_frames, state.kind)
            if state.kind == "unknown":
                return StateInspection("unknown", state.id, "unknown_screen", self._stable_frames, state.kind)
            return StateInspection("blocked", state.id, state.kind, self._stable_frames, state.kind)
        return StateInspection("unknown", None, "unstable", self._stable_frames)

    def _blocked(self) -> StateInspection:
        self._reset_stability()
        return StateInspection("blocked", None, "excluded", 0)

    def _unknown(self, reason: str) -> StateInspection:
        self._reset_stability()
        return StateInspection("unknown", None, reason, 0)

    def _reset_stability(self) -> None:
        self._last_layout = None
        self._last_candidate = None
        self._last_generation = None
        self._last_sequence = None
        self._stable_frames = 0


def _finite_number(value: object) -> bool:
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _score_number(value: object) -> bool:
    if not _finite_number(value):
        return False
    return 0 <= value <= 1
