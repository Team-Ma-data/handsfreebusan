"""역 마스터 로더 + 느슨한 역명 매칭 (한국어/영어/오타 허용)."""

from __future__ import annotations

import json
import re
import unicodedata
from difflib import get_close_matches
from pathlib import Path
from typing import Optional

DATA = Path(__file__).resolve().parent.parent / "data"
_RAW = json.loads((DATA / "stations.json").read_text(encoding="utf-8"))
STATIONS: list[dict] = _RAW["stations"]
BY_NAME: dict[str, dict] = {s["name"]: s for s in STATIONS}


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower().strip()
    s = re.sub(r"(역|station|stn\.?|metro)$", "", s).strip()
    return re.sub(r"[\s·.\-_,]", "", s)


_INDEX: dict[str, str] = {}
for _s in STATIONS:
    _INDEX[_norm(_s["name"])] = _s["name"]
    _INDEX[_norm(_s.get("name_en", ""))] = _s["name"]
_INDEX.pop("", None)

#: 관광객이 실제로 말하는 지명 → 역명
ALIASES = {
    "haeundaebeach": "해운대", "해운대해수욕장": "해운대", "해운대비치": "해운대",
    "gwangalli": "광안", "광안리": "광안", "gwangallibeach": "광안",
    "gamcheon": "토성", "감천문화마을": "토성", "gamcheonculturevillage": "토성",
    "gukjemarket": "남포", "국제시장": "남포", "biff": "남포", "비프광장": "남포",
    "jagalchimarket": "자갈치", "자갈치시장": "자갈치",
    "shinsegae": "센텀시티", "신세계": "센텀시티",
    "ktx": "부산역", "busanktx": "부산역",
    "airport": "공항", "gimhae": "공항", "김해공항": "공항",
    "sajikstadium": "사직", "사직구장": "사직",
    "seomyeon": "서면", "lottedutyfree": "서면",
}


def resolve(name: Optional[str]) -> Optional[dict]:
    """'Haeundae Beach', '해운대역', 'seomyun' 등을 역 레코드로 해석."""
    if not name:
        return None
    key = _norm(name)
    if key in ALIASES:
        return BY_NAME.get(ALIASES[key])
    if key in _INDEX:
        return BY_NAME[_INDEX[key]]
    hit = get_close_matches(key, list(_INDEX.keys()) + list(ALIASES.keys()), n=1, cutoff=0.75)
    if hit:
        h = hit[0]
        return BY_NAME.get(ALIASES.get(h) or _INDEX.get(h, ""))
    return None


def nearest(lat: float, lng: float) -> Optional[dict]:
    import math

    def d(s):
        return math.hypot(s["lat"] - lat, (s["lng"] - lng) * math.cos(math.radians(lat)))

    return min(STATIONS, key=d) if STATIONS else None


def known_names() -> list[str]:
    return [s["name"] for s in STATIONS]
