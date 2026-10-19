"""L4 Domain — Stage IO contract types."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class StageIOContract:
    requires: list[str] = field(default_factory=list)   # must exist in State
    optional: list[str] = field(default_factory=list)   # may exist in State
    provides: list[str] = field(default_factory=list)   # always written by this Stage
    optional_provides: list[str] = field(default_factory=list)
    # ^ may be written by this Stage on some paths; declared for traceability but
    #   NOT part of the has_all() early-termination check (mirror of `optional`).

    def validate(self, state_fields: set[str]) -> list[str]:
        """Return list of missing required fields."""
        missing = [f for f in self.requires if f not in state_fields]
        return missing

    def all_provides(self) -> list[str]:
        """Union of guaranteed + optional outputs, for downstream link checks."""
        result = list(self.provides)
        result.extend(p for p in self.optional_provides if p not in result)
        return result
