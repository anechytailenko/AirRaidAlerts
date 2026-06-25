"""Canonical Ukrainian oblast reference data + a tolerant name resolver.

This is real geographic master data (region names, approximate centroids, and land
borders) — NOT synthetic observations. IDs are app-assigned, alphabetical by name_en.
"""
from __future__ import annotations

import re

# (id, name_en, name_uk, centroid_lat, centroid_lon)
OBLASTS: list[tuple[int, str, str, float, float]] = [
    (1, "Cherkasy", "Черкаська область", 49.30, 31.50),
    (2, "Chernihiv", "Чернігівська область", 51.50, 31.30),
    (3, "Chernivtsi", "Чернівецька область", 48.30, 25.95),
    (4, "Crimea", "Автономна Республіка Крим", 45.30, 34.40),
    (5, "Dnipropetrovsk", "Дніпропетровська область", 48.45, 34.90),
    (6, "Donetsk", "Донецька область", 48.00, 37.80),
    (7, "Ivano-Frankivsk", "Івано-Франківська область", 48.65, 24.70),
    (8, "Kharkiv", "Харківська область", 49.85, 36.60),
    (9, "Kherson", "Херсонська область", 46.65, 33.40),
    (10, "Khmelnytskyi", "Хмельницька область", 49.40, 27.00),
    (11, "Kirovohrad", "Кіровоградська область", 48.50, 32.25),
    (12, "Kyiv", "Київська область", 50.05, 30.75),
    (13, "Kyiv City", "м. Київ", 50.45, 30.52),
    (14, "Luhansk", "Луганська область", 48.60, 39.30),
    (15, "Lviv", "Львівська область", 49.60, 24.00),
    (16, "Mykolaiv", "Миколаївська область", 47.20, 31.50),
    (17, "Odesa", "Одеська область", 46.50, 30.40),
    (18, "Poltava", "Полтавська область", 49.65, 33.40),
    (19, "Rivne", "Рівненська область", 50.60, 26.25),
    (20, "Sevastopol", "м. Севастополь", 44.60, 33.52),
    (21, "Sumy", "Сумська область", 51.00, 34.30),
    (22, "Ternopil", "Тернопільська область", 49.40, 25.60),
    (23, "Vinnytsia", "Вінницька область", 49.05, 28.45),
    (24, "Volyn", "Волинська область", 51.00, 25.30),
    (25, "Zakarpattia", "Закарпатська область", 48.40, 23.30),
    (26, "Zaporizhzhia", "Запорізька область", 47.30, 35.30),
    (27, "Zhytomyr", "Житомирська область", 50.45, 28.65),
]

_NAME_TO_ID = {name_en: i for i, name_en, *_ in OBLASTS}

# Undirected real land-border pairs (by name_en). Stored symmetrically at seed time.
ADJACENCY_PAIRS: list[tuple[str, str]] = [
    ("Volyn", "Rivne"), ("Volyn", "Lviv"),
    ("Rivne", "Lviv"), ("Rivne", "Ternopil"), ("Rivne", "Khmelnytskyi"), ("Rivne", "Zhytomyr"),
    ("Lviv", "Ternopil"), ("Lviv", "Ivano-Frankivsk"), ("Lviv", "Zakarpattia"),
    ("Zakarpattia", "Ivano-Frankivsk"),
    ("Ivano-Frankivsk", "Ternopil"), ("Ivano-Frankivsk", "Chernivtsi"),
    ("Ternopil", "Khmelnytskyi"), ("Ternopil", "Chernivtsi"),
    ("Chernivtsi", "Vinnytsia"), ("Chernivtsi", "Khmelnytskyi"),
    ("Khmelnytskyi", "Zhytomyr"), ("Khmelnytskyi", "Vinnytsia"),
    ("Zhytomyr", "Kyiv"), ("Zhytomyr", "Vinnytsia"),
    ("Vinnytsia", "Cherkasy"), ("Vinnytsia", "Kirovohrad"), ("Vinnytsia", "Odesa"),
    ("Kyiv", "Kyiv City"), ("Kyiv", "Chernihiv"), ("Kyiv", "Cherkasy"), ("Kyiv", "Poltava"),
    ("Chernihiv", "Sumy"), ("Chernihiv", "Poltava"),
    ("Sumy", "Poltava"), ("Sumy", "Kharkiv"),
    ("Poltava", "Cherkasy"), ("Poltava", "Kirovohrad"), ("Poltava", "Dnipropetrovsk"), ("Poltava", "Kharkiv"),
    ("Kharkiv", "Dnipropetrovsk"), ("Kharkiv", "Donetsk"), ("Kharkiv", "Luhansk"),
    ("Luhansk", "Donetsk"),
    ("Donetsk", "Dnipropetrovsk"), ("Donetsk", "Zaporizhzhia"),
    ("Dnipropetrovsk", "Zaporizhzhia"), ("Dnipropetrovsk", "Kherson"),
    ("Dnipropetrovsk", "Mykolaiv"), ("Dnipropetrovsk", "Kirovohrad"),
    ("Cherkasy", "Kirovohrad"),
    ("Kirovohrad", "Mykolaiv"), ("Kirovohrad", "Odesa"),
    ("Zaporizhzhia", "Kherson"),
    ("Kherson", "Mykolaiv"), ("Kherson", "Crimea"),
    ("Mykolaiv", "Odesa"),
    ("Crimea", "Sevastopol"),
]

# Explicit aliases (normalized form -> id) for tricky / variant strings.
_ALIASES: dict[str, int] = {
    "kyiv city": 13, "kyivcity": 13, "kiev city": 13, "m kyiv": 13, "misto kyiv": 13,
    "kyiv": 12, "kyiv oblast": 12, "kyivska": 12, "kiev": 12, "kievska": 12,
    "crimea": 4, "ar crimea": 4, "autonomous republic of crimea": 4, "krym": 4,
    "sevastopol": 20,
    "dnipro": 5, "dnipropetrovsk": 5,
    "kharkov": 8, "zaporizhia": 26, "zaporozhye": 26, "transcarpathia": 25,
    "ivano frankivsk": 7, "kropyvnytskyi": 11, "odessa": 17,
    # Adjectival transliterations as they appear in the Vadimkin EN dataset
    # ("<adjective> oblast" → 'oblast' is stripped by _normalize, leaving the adjective).
    "cherkaska": 1, "chernihivska": 2, "chernivetska": 3, "dnipropetrovska": 5,
    "donetska": 6, "ivano frankivska": 7, "kharkivska": 8, "khersonska": 9,
    "khmelnytska": 10, "kirovohradska": 11, "kyivska oblast": 12, "luhanska": 14,
    "lvivska": 15, "mykolaivska": 16, "odeska": 17, "poltavska": 18, "rivnenska": 19,
    "sumska": 21, "ternopilska": 22, "vinnytska": 23, "volynska": 24, "zakarpatska": 25,
    "zaporizka": 26, "zhytomyrska": 27,
}


def _normalize(s: str) -> str:
    s = s.strip().lower()
    s = s.replace("’", "'").replace("`", "'")
    # strip region designators in EN and UK
    for token in ["oblast", "region", "область", "обл.", "обл", "м.", "місто"]:
        s = s.replace(token, " ")
    s = re.sub(r"[^a-z0-9а-яіїєґ' ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def resolve_oblast(name: str | None) -> int | None:
    """Resolve a raw region string to a canonical oblast id, else None (quarantine)."""
    if not name:
        return None
    norm = _normalize(name)
    if norm in _ALIASES:
        return _ALIASES[norm]
    # direct match against English canonical names
    for i, name_en, name_uk, *_ in OBLASTS:
        if norm == _normalize(name_en) or norm == _normalize(name_uk):
            return i
    # last resort: alias keys by substring (longest first to avoid 'kyiv' eating 'kyiv city')
    for key in sorted(_ALIASES, key=len, reverse=True):
        if key in norm:
            return _ALIASES[key]
    return None
