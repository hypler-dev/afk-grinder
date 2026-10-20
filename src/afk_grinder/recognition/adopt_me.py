"""Small English allowlist for supervised Adopt Me popup recovery.

OCR labels are evidence, not input authority. Unknown and protected screens
never produce a click target. This is deliberately not a general UI agent.
"""

from dataclasses import dataclass
import math

from .matcher import LabelHit
from .observation import Layout, Observation

# Fixed, application-owned expressions. Raw recognized text stays in the worker.
LABELS = {
    "protected_login": r".*\b(?:password|sign\s*in|log\s*in|username|verification|captcha)\b.*",
    "protected_trade": r".*\b(?:trade|trading|accept|confirm)\b.*",
    "protected_purchase": r".*(?:\b(?:buy|purchase|robux)\b|R\$).*",
    "protected": r".*\b(?:buy|purchase|robux|trade|trading|accept|confirm|password|sign\s*in|log\s*in|security|banned|kicked)\b.*",
    "account_conflict": r".*(?:same account|another device|error\s*code\s*:\s*(?:264|267|268|273|280)).*",
    "bank": r"BANK[!.]?",
    "bank_reason": r"For Playing Adopt Me[!.]?",
    "cash_out": r"CASH\s*OUT[!.]?",
    "disconnected": r"Disconnected",
    "reconnect": r"Reconnect",
    "leave": r"Leave",
    "idle_reason": r"(?:You were )?disconnected for being idle (?:20|twenty) minutes[.!]?",
    "idle_code": r"\(?Error\s*Code\s*:\s*278\)?",
    "connection_reason": r"Please check your internet connection and try again[.!]?",
    "connection_code": r"\(?Error\s*Code\s*:\s*277\)?",
}


@dataclass(frozen=True)
class PopupEvidence:
    state: str
    reason: str
    layout: Layout
    captured_at: float
    sequence: int
    generation: int
    button: tuple[int, int, int, int] | None = None
    privacy: str = "none"

    @property
    def point(self) -> tuple[float, float] | None:
        if self.button is None:
            return None
        x, y, width, height = self.button
        return x + width / 2, y + height / 2


def _color(pixels: bytes, width: int, x: int, y: int, style: str) -> bool:
    b, g, r = pixels[(y * width + x) * 3:(y * width + x) * 3 + 3]
    if style == "white":
        return min(b, g, r) >= 220 and max(b, g, r) - min(b, g, r) <= 20
    return g >= 90 and g > r * 1.15 and g > b * 1.05


def _button(observation: Observation, hit: LabelHit, style: str) -> tuple[int, int, int, int] | None:
    """Find the bounded solid button containing its recognized text."""
    width, height = observation.layout.physical_size
    x, y, w, h = hit.box
    seeds = [(x + w // 2, max(0, y - 3)), (x + w // 2, min(height - 1, y + h + 2)),
             (max(0, x - 3), y + h // 2)]
    seed = next((p for p in seeds if _color(observation.pixels, width, *p, style)), None)
    if seed is None:
        return None
    seen = {seed}
    stack = [seed]
    left = right = seed[0]
    top = bottom = seed[1]
    limit = min(100_000, max(1, width * height // 8))
    while stack:
        px, py = stack.pop()
        left, right = min(left, px), max(right, px)
        top, bottom = min(top, py), max(bottom, py)
        if right - left > width * .45 or bottom - top > height * .18 or len(seen) > limit:
            return None
        for nx, ny in ((px - 1, py), (px + 1, py), (px, py - 1), (px, py + 1)):
            if (0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen
                    and _color(observation.pixels, width, nx, ny, style)):
                seen.add((nx, ny))
                stack.append((nx, ny))
    bw, bh = right - left + 1, bottom - top + 1
    if (not left <= x < x + w <= right + 1 or not top <= y < y + h <= bottom + 1
            or not 1.6 <= bw / bh <= 9 or bw < w + 8 or bh < h + 4
            or len(seen) / (bw * bh) < .65):
        return None
    return left, top, bw, bh


def inspect(observation: Observation, hits: tuple[LabelHit, ...], *, now: float) -> PopupEvidence:
    def result(state: str, reason: str, button=None, privacy="none") -> PopupEvidence:
        return PopupEvidence(state, reason, observation.layout, observation.captured_at,
                             observation.sequence, observation.generation, button, privacy)
    if (observation.layout.region_kind != "client" or not observation.layout.content_verified
            or type(now) not in (int, float) or not math.isfinite(now)
            or now < observation.captured_at or now - observation.captured_at > .5):
        return result("unknown", "Fresh calibrated content is required.")
    width, height = observation.layout.physical_size
    labels: dict[str, list[LabelHit]] = {}
    protected = set()
    for hit in hits:
        if (type(hit) is not LabelHit or hit.label_id not in LABELS
                or type(hit.score) not in (int, float) or not math.isfinite(hit.score)
                or not 0 <= hit.score <= 1 or type(hit.box) is not tuple or len(hit.box) != 4
                or any(type(value) is not int for value in hit.box)):
            return result("unknown", "Recognition evidence is invalid.")
        x, y, w, h = hit.box
        if min(x, y) < 0 or min(w, h) <= 0 or x + w > width or y + h > height:
            return result("unknown", "Recognition evidence is invalid.")
        if (hit.label_id.startswith("protected") or hit.label_id == "account_conflict") and hit.score >= .3:
            privacy = {"protected_login": "login", "protected_trade": "trade",
                       "protected_purchase": "purchase"}.get(hit.label_id, "restricted")
            protected.add(privacy)
        if hit.score >= .9:
            labels.setdefault(hit.label_id, []).append(hit)
    if protected:
        privacy = next(kind for kind in ("login", "restricted", "trade", "purchase") if kind in protected)
        return result("protected", "Purchase, trade, login or restricted screen blocked.", privacy=privacy)
    if any(len(values) != 1 for values in labels.values()):
        return result("unknown", "Ambiguous popup evidence.")
    one = {label: values[0] for label, values in labels.items()}
    if {"bank", "bank_reason", "cash_out"} <= one.keys():
        if {"disconnected", "reconnect", "leave"} & one.keys():
            return result("unknown", "Conflicting popup evidence.")
        a, b, c = (one[label].box for label in ("bank", "bank_reason", "cash_out"))
        if (a[1] < b[1] < c[1] and all(width * .15 < box[0] + box[2] / 2 < width * .85
                                       for box in (a, b, c))):
            button = _button(observation, one["cash_out"], "green")
            if button:
                return result("bank_reward", "Adopt Me play-time reward identified.", button)
    if {"disconnected", "reconnect", "leave"} <= one.keys():
        allowed = ({"idle_reason", "idle_code"} <= one.keys()
                   or {"connection_reason", "connection_code"} <= one.keys())
        a, b, c = (one[label].box for label in ("disconnected", "leave", "reconnect"))
        if (allowed and a[1] < b[1] and b[0] + b[2] < c[0]
                and abs(b[1] - c[1]) <= max(b[3], c[3])
                and width * .3 < a[0] + a[2] / 2 < width * .7
                and height * .15 < a[1] < height * .7):
            button = _button(observation, one["reconnect"], "white")
            if button:
                return result("disconnected", "Known idle or connection dialog identified.", button)
    return result("unknown", "Unsupported or incomplete screen; input paused.")


class Stability:
    """Require two fresh consecutive observations of the same approved target."""
    def __init__(self):
        self.previous: PopupEvidence | None = None

    def accept(self, evidence: PopupEvidence) -> bool:
        previous, self.previous = self.previous, evidence
        if evidence.button is None or evidence.state not in {"bank_reward", "disconnected"}:
            self.previous = None
            return False
        if (previous is None or previous.state != evidence.state or previous.layout != evidence.layout
                or previous.generation != evidence.generation or previous.sequence + 1 != evidence.sequence
                or not previous.captured_at < evidence.captured_at
                or previous.button is None):
            return False
        tolerance = max(2, min(evidence.layout.physical_size) * .01)
        return all(abs(a - b) <= tolerance for a, b in zip(previous.button, evidence.button))
