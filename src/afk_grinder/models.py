"""Shared immutable data and native adapter contract."""

from dataclasses import dataclass
from typing import Protocol

KEYS = frozenset({"w", "a", "s", "d", "e", "space", "up", "down", "left", "right"})
BUTTONS = frozenset({"left", "right"})


@dataclass(frozen=True)
class Target:
    pid: int
    token: str
    executable: str
    identifier: str

    @property
    def is_roblox(self) -> bool:
        return self.identifier == "com.roblox.RobloxPlayer" or (
            self.identifier == "win32"
            and self.executable.casefold() in {"robloxplayerbeta.exe", "robloxplayer.exe"}
        )


@dataclass(frozen=True)
class Step:
    action: str
    duration_ms: int = 0
    key: str = ""
    button: str = ""


@dataclass(frozen=True)
class Workflow:
    name: str
    steps: tuple[Step, ...]


class Backend(Protocol):
    def foreground(self) -> Target | None: ...
    def readiness(self) -> list[str]: ...
    def escape_pressed(self) -> bool: ...
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...
    def mouse_down(self, button: str) -> None: ...
    def mouse_up(self, button: str) -> None: ...
