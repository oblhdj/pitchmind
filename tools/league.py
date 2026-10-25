"""Fictional league data: two clubs with full squads. All names are invented.

Used by the mock stream now and by the simulator later.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime

from pitchmind_contracts import (
    MatchMeta,
    Player,
    PlayerAttributes,
    Position,
    Team,
    TeamColors,
    TeamSide,
)

# number, full name, short name, position, nationality
HOME_SQUAD = [
    (1, "Tomás Varga", "Varga", Position.GK, "HUN"),
    (2, "Kwame Asante-Reid", "Asante-Reid", Position.FB, "ENG"),
    (4, "Lucas Moreau", "Moreau", Position.CB, "FRA"),
    (5, "Dani Okafor", "Okafor", Position.CB, "NGA"),
    (3, "Ilyas Benali", "Benali", Position.FB, "MAR"),
    (6, "Jonas Lindqvist", "Lindqvist", Position.DM, "SWE"),
    (8, "Mateo Ferraz", "Ferraz", Position.CM, "POR"),
    (10, "Rayan Haddad", "Haddad", Position.AM, "TUN"),
    (7, "Leo Whitcombe", "Whitcombe", Position.W, "ENG"),
    (11, "Kenji Arai", "Arai", Position.W, "JPN"),
    (9, "Sami Kaya", "Kaya", Position.ST, "TUR"),
    (12, "Owen Pryce", "Pryce", Position.GK, "WAL"),
    (14, "Bruno Salvi", "Salvi", Position.CM, "ITA"),
    (15, "Noah Castell", "Castell", Position.CB, "ESP"),
    (17, "Malik Diarra", "Diarra", Position.W, "MLI"),
    (19, "Finn O'Rourke", "O'Rourke", Position.ST, "IRL"),
]

AWAY_SQUAD = [
    (1, "Erik Sandvik", "Sandvik", Position.GK, "NOR"),
    (2, "Marcus Bellamy", "Bellamy", Position.FB, "ENG"),
    (5, "Thiago Nunes", "Nunes", Position.CB, "BRA"),
    (6, "Pavel Novak", "Novak", Position.CB, "CZE"),
    (3, "Yusuf Demir", "Demir", Position.FB, "TUR"),
    (4, "Oliver Grant", "Grant", Position.DM, "SCO"),
    (8, "Adrien Lefèvre", "Lefèvre", Position.DM, "FRA"),
    (10, "Nico Albers", "Albers", Position.AM, "GER"),
    (7, "Diego Herrera", "Herrera", Position.W, "ARG"),
    (11, "Samuel Mensah", "Mensah", Position.W, "GHA"),
    (9, "Viktor Halvorsen", "Halvorsen", Position.ST, "DEN"),
    (13, "Luca Ricci", "Ricci", Position.GK, "ITA"),
    (14, "Hamza Idrissi", "Idrissi", Position.CM, "MAR"),
    (16, "Jake Mallory", "Mallory", Position.CB, "ENG"),
    (18, "Kofi Boateng-Lowe", "Boateng-Lowe", Position.W, "GHA"),
    (20, "Ivan Petrov", "Petrov", Position.ST, "BUL"),
]

# Base attribute profile per position: pace, passing, finishing, dribbling, defending, stamina
_PROFILES: dict[Position, tuple[int, int, int, int, int, int]] = {
    Position.GK: (45, 60, 15, 30, 40, 60),
    Position.CB: (65, 65, 35, 50, 80, 75),
    Position.FB: (78, 70, 45, 68, 72, 82),
    Position.DM: (68, 78, 50, 65, 76, 85),
    Position.CM: (72, 80, 62, 74, 64, 84),
    Position.AM: (76, 84, 74, 82, 45, 78),
    Position.W: (86, 74, 70, 82, 40, 80),
    Position.ST: (80, 66, 82, 74, 35, 76),
}

# Hand-tuned stars so the demo storyline is plausible.
_OVERRIDES: dict[str, dict[str, int]] = {
    "H10": {"passing": 90, "dribbling": 88, "finishing": 80},
    "H11": {"pace": 94},
    "H9": {"finishing": 85},
    "A9": {"finishing": 86},
    "A10": {"passing": 87},
    "A1": {"defending": 70},
}


def _attributes(pid: str, position: Position, rng: random.Random) -> PlayerAttributes:
    names = ("pace", "passing", "finishing", "dribbling", "defending", "stamina")
    values = {
        n: max(1, min(99, base + rng.randint(-6, 6)))
        for n, base in zip(names, _PROFILES[position], strict=True)
    }
    values.update(_OVERRIDES.get(pid, {}))
    return PlayerAttributes(**values)


def _team(
    squad: list[tuple[int, str, str, Position, str]],
    *,
    side: TeamSide,
    team_id: str,
    name: str,
    short_name: str,
    colors: TeamColors,
    formation: str,
    rng: random.Random,
) -> Team:
    prefix = "H" if side is TeamSide.HOME else "A"
    players = [
        Player(
            id=f"{prefix}{number}",
            name=full,
            short_name=short,
            number=number,
            position=pos,
            nationality=nat,
            attributes=_attributes(f"{prefix}{number}", pos, rng),
        )
        for number, full, short, pos, nat in squad
    ]
    return Team(
        id=team_id,
        name=name,
        short_name=short_name,
        side=side,
        colors=colors,
        formation=formation,
        players=players,
        starting_xi=[p.id for p in players[:11]],
    )


def build_match_meta(match_id: str = "M001", seed: int = 7) -> MatchMeta:
    rng = random.Random(seed)
    home = _team(
        HOME_SQUAD, side=TeamSide.HOME, team_id="north-city", name="North City FC", short_name="NCF",
        colors=TeamColors(primary="#1F4E79", secondary="#FFFFFF"), formation="4-3-3", rng=rng,
    )
    away = _team(
        AWAY_SQUAD, side=TeamSide.AWAY, team_id="harbour-united", name="Harbour United", short_name="HBU",
        colors=TeamColors(primary="#C62828", secondary="#1A1A1A"), formation="4-2-3-1", rng=rng,
    )
    return MatchMeta(
        match_id=match_id,
        competition="Synthetic Premier Division",
        venue="Northgate Park",
        kickoff=datetime(2026, 10, 25, 15, 0, tzinfo=UTC),
        seed=seed,
        home=home,
        away=away,
    )
