"""PitchMind moment detection: the moments that matter, with evidence."""

from .context import MatchContext
from .detector import MomentDetector, detect
from .rules import Rule, default_rules

__all__ = ["MatchContext", "MomentDetector", "Rule", "default_rules", "detect"]
