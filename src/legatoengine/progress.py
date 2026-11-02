"""Progress reporting for long conversions."""

from __future__ import annotations

from typing import Callable

ProgressFn = Callable[[str, float], None]  # (stage label, overall fraction 0..1)


def ignore(stage: str, fraction: float) -> None:
    pass


class Stages:
    """Splits one progress bar between named stages by weight.

    stages = Stages(report, [("separate", "Separating instruments", 3), ...])
    step = stages.start("separate")  # step(0.5) -> halfway through that stage
    """

    def __init__(self, report: ProgressFn | None, stages: list[tuple[str, str, float]]):
        self.report = report or ignore
        total = sum(w for _, _, w in stages)
        self._spans: dict[str, tuple[str, float, float]] = {}
        at = 0.0
        for key, label, weight in stages:
            self._spans[key] = (label, at / total, (at + weight) / total)
            at += weight

    def start(self, key: str, label: str | None = None) -> Callable[[float], None]:
        """``label`` replaces the stage's usual one."""
        usual, begin, end = self._spans[key]
        label = label or usual
        self.report(label, begin)

        def step(fraction: float) -> None:
            # clamped, since rounding can put the end a hair past where the next stage begins
            self.report(label, min(begin + (end - begin) * min(max(fraction, 0.0), 1.0), end))

        return step

    def done(self) -> None:
        self.report("Done", 1.0)
