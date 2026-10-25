"""Event Hubs topic names. Partition key is always ``match_id``."""

from enum import StrEnum


class Topic(StrEnum):
    MATCH_EVENTS = "match-events"
    MATCH_STATS = "match-stats"
    MATCH_MOMENTS = "match-moments"
    MATCH_INSIGHTS = "match-insights"
    MATCH_OVERLAYS = "match-overlays"
