"""Canonical list of the 30 NBA teams and name normalization.

Every source maps its team labels onto these abbreviations. An unrecognized
label is a hard error -- we never guess which team a row belongs to.
"""

# abbr, city, nickname, conference, division
TEAMS = [
    ("BOS", "Boston", "Celtics", "East", "Atlantic"),
    ("BKN", "Brooklyn", "Nets", "East", "Atlantic"),
    ("NYK", "New York", "Knicks", "East", "Atlantic"),
    ("PHI", "Philadelphia", "76ers", "East", "Atlantic"),
    ("TOR", "Toronto", "Raptors", "East", "Atlantic"),
    ("CHI", "Chicago", "Bulls", "East", "Central"),
    ("CLE", "Cleveland", "Cavaliers", "East", "Central"),
    ("DET", "Detroit", "Pistons", "East", "Central"),
    ("IND", "Indiana", "Pacers", "East", "Central"),
    ("MIL", "Milwaukee", "Bucks", "East", "Central"),
    ("ATL", "Atlanta", "Hawks", "East", "Southeast"),
    ("CHA", "Charlotte", "Hornets", "East", "Southeast"),
    ("MIA", "Miami", "Heat", "East", "Southeast"),
    ("ORL", "Orlando", "Magic", "East", "Southeast"),
    ("WAS", "Washington", "Wizards", "East", "Southeast"),
    ("DEN", "Denver", "Nuggets", "West", "Northwest"),
    ("MIN", "Minnesota", "Timberwolves", "West", "Northwest"),
    ("OKC", "Oklahoma City", "Thunder", "West", "Northwest"),
    ("POR", "Portland", "Trail Blazers", "West", "Northwest"),
    ("UTA", "Utah", "Jazz", "West", "Northwest"),
    ("GSW", "Golden State", "Warriors", "West", "Pacific"),
    ("LAC", "Los Angeles", "Clippers", "West", "Pacific"),
    ("LAL", "Los Angeles", "Lakers", "West", "Pacific"),
    ("PHX", "Phoenix", "Suns", "West", "Pacific"),
    ("SAC", "Sacramento", "Kings", "West", "Pacific"),
    ("DAL", "Dallas", "Mavericks", "West", "Southwest"),
    ("HOU", "Houston", "Rockets", "West", "Southwest"),
    ("MEM", "Memphis", "Grizzlies", "West", "Southwest"),
    ("NOP", "New Orleans", "Pelicans", "West", "Southwest"),
    ("SAS", "San Antonio", "Spurs", "West", "Southwest"),
]

ABBRS = [t[0] for t in TEAMS]
assert len(ABBRS) == 30 and len(set(ABBRS)) == 30

# Abbreviations other sites use that differ from ours.
_EXTRA_ALIASES = {
    "BRK": "BKN", "BKN": "BKN", "NJN": "BKN",
    "CHO": "CHA", "PHO": "PHX", "GS": "GSW", "NY": "NYK", "SA": "SAS",
    "NO": "NOP", "NOR": "NOP", "UTAH": "UTA", "WSH": "WAS", "LA CLIPPERS": "LAC",
    "LA LAKERS": "LAL", "SIXERS": "PHI", "BLAZERS": "POR", "WOLVES": "MIN",
    "CAVS": "CLE", "MAVS": "DAL",
}


def _key(s):
    return " ".join(s.replace(".", "").upper().split())


_ALIASES = {}
for abbr, city, nick, _conf, _div in TEAMS:
    for label in (abbr, nick, f"{city} {nick}"):
        _ALIASES[_key(label)] = abbr
for label, abbr in _EXTRA_ALIASES.items():
    _ALIASES[_key(label)] = abbr


def normalize(label):
    """Return the canonical abbreviation for a team label, or raise."""
    abbr = _ALIASES.get(_key(label))
    if abbr is None:
        raise ValueError(f"Unrecognized team label: {label!r}")
    return abbr


def team_meta():
    return [
        {"abbr": a, "city": c, "nickname": n, "name": f"{c} {n}", "conf": conf, "div": div}
        for a, c, n, conf, div in TEAMS
    ]
