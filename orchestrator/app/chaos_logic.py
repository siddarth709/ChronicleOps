from dataclasses import dataclass
from enum import Enum

class Action(str, Enum):
    NOOP = "noop"
    MARK_DOWN_AND_RESTART = "mark_down_and_restart"
    MARK_RECOVERED = "mark_recovered"

@dataclass
class ExperimentState:
    healthy: bool
    down_at: float | None
    recovered_at: float | None

def next_action(state: ExperimentState, now: float) -> tuple[Action, float | None]:
    if state.recovered_at is not None:
        return Action.NOOP, None

    if state.down_at is None:
        if state.healthy:
            return Action.NOOP, None
        return Action.MARK_DOWN_AND_RESTART, None

    if not state.healthy:
        return Action.NOOP, None

    mttr = now - state.down_at
    return Action.MARK_RECOVERED, mttr

def is_expired(expires_at: float, now: float) -> bool:
    return now >= expires_at