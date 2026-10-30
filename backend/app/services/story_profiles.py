"""Story profiles: what to emphasise for each type of story.

These are starting priors written from general storytelling craft, not measured on data yet.
Stages receive the profile as plain data in their prompt input; changing a profile never needs a prompt edit.
"""

PROFILES: dict[str, dict] = {
    "general": {
        "label": "General",
        "protect": ["plot points and reveals", "character decisions", "setup that is paid off later"],
        "filler": ["repeated information", "scenery with no plot change", "small talk"],
        "episode_seconds": 600,
    },
    "mystery": {
        "label": "Mystery / thriller",
        "protect": ["clues and red herrings", "reveals", "who knows what and when", "alibis and timing"],
        "filler": ["scenery", "repeated suspicion that adds no new fact"],
        "episode_seconds": 600,
    },
    "romance": {
        "label": "Romance",
        "protect": ["relationship turning points", "small gestures and glances", "key conversations"],
        "filler": ["plot logistics between relationship beats", "repeated misunderstandings"],
        "episode_seconds": 600,
    },
    "fantasy_scifi": {
        "label": "Fantasy / science fiction",
        "protect": ["world rules", "the first sight of places, factions and technology", "setup that pays off later"],
        "filler": ["repeated travel", "a second explanation of a rule already shown"],
        "episode_seconds": 720,
    },
    "literary": {
        "label": "Literary / character-driven",
        "protect": ["interior change", "recurring motifs", "quiet scenes that show a character"],
        "filler": ["very little; cut only exact repetition"],
        "episode_seconds": 900,
    },
    "horror": {
        "label": "Horror",
        "protect": ["dread build-up", "the first appearance of the threat", "isolation and rules of the threat"],
        "filler": ["safe scenes that add no tension or information"],
        "episode_seconds": 600,
    },
    "comedy": {
        "label": "Comedy",
        "protect": ["set-ups with their punchlines", "running gags", "character quirks"],
        "filler": ["scenes with no joke, setup or plot step"],
        "episode_seconds": 420,
    },
    "adventure": {
        "label": "Adventure / journey",
        "protect": ["the goal of each stage", "dangers", "changes in the group of companions"],
        "filler": ["travel that repeats the same obstacle"],
        "episode_seconds": 600,
    },
}

# First keyword found in the genre text decides; the user can set the genre on the series.
KEYWORDS = [
    ("mystery", ("mystery", "thriller", "crime", "detective", "noir", "suspense")),
    ("romance", ("romance", "love story", "romantic")),
    ("horror", ("horror", "gothic", "ghost")),
    ("comedy", ("comedy", "humor", "humour", "satire", "farce")),
    ("fantasy_scifi", ("fantasy", "science fiction", "sci-fi", "scifi", "space opera", "dystopia")),
    ("adventure", ("adventure", "quest", "journey", "voyage")),
    ("literary", ("literary", "drama", "psychological", "coming-of-age", "classic")),
]


def resolve_profile(genre: str | None) -> tuple[str, dict]:
    text = (genre or "").lower()
    for key, words in KEYWORDS:
        if any(word in text for word in words):
            return key, PROFILES[key]
    return "general", PROFILES["general"]
