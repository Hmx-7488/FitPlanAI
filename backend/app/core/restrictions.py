"""Canonical health and dietary restriction tags used across services."""

from collections.abc import Iterable


_INJURY_ALIASES = {
    "knee": ("knee", "knee pain", "knee injury", "膝", "膝盖", "膝关节"),
    "back": (
        "back pain",
        "back injury",
        "lower back",
        "lumbar",
        "腰",
        "腰椎",
        "下背",
    ),
    "shoulder": ("shoulder", "shoulder pain", "shoulder injury", "肩", "肩袖"),
}

_SOURCE_ALIASES = {
    "milk": ("milk", "dairy", "lactose", "牛奶", "乳制品", "乳糖", "奶"),
    "fish": ("fish", "鱼", "鱼类", "水产"),
    "shellfish": (
        "shellfish",
        "shrimp",
        "prawn",
        "crab",
        "贝壳",
        "甲壳",
        "虾",
        "蟹",
    ),
    "animal": ("animal", "meat", "动物", "肉类", "荤食"),
}


def _normalized_text(value: object) -> str:
    return " ".join(str(value).strip().lower().replace("_", "-").replace("-", " ").split())


def canonical_injury_tags(injuries: Iterable[object] | None) -> set[str]:
    """Map profile injury values such as ``back_pain`` or ``腰痛`` to stable tags."""
    tags: set[str] = set()
    for injury in injuries or ():
        normalized = _normalized_text(injury)
        if not normalized:
            continue
        for tag, aliases in _INJURY_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                tags.add(tag)
    return tags


def canonical_source_restrictions(restrictions: Iterable[object] | None) -> set[str]:
    """Map allergy/forbidden-food values to supplement source tags."""
    tags: set[str] = set()
    for restriction in restrictions or ():
        normalized = _normalized_text(restriction)
        if not normalized:
            continue
        if "seafood" in normalized or "海鲜" in normalized:
            tags.update(("fish", "shellfish"))
        for tag, aliases in _SOURCE_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                tags.add(tag)
    return tags
