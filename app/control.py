"""Runtime switches shared by all venues (dashboard-controlled)."""

from dataclasses import dataclass


@dataclass
class Control:
    # Global kill-switch: blocks NEW entries on every venue; exits keep mirroring.
    paused: bool = False
