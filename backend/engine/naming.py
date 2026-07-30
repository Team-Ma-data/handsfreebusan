# -*- coding: utf-8 -*-
"""역명 표기 정규화.

발제 데이터 5종은 같은 역을 서로 다르게 적는다. 정규 키는 역번호이지만
#3.1 엘리베이터/#3.2 에스컬레이터/#4.x 편의시설에는 역번호가 없어
(호선, 역명) 쌍으로 조인해야 하므로 표기 통일이 선행되어야 한다.

관측된 변형 유형:
  - 호선 접두: '1서면', '2서면', '3연산', '4동래'  (환승역 중복 역명 구분용)
  - 중점 문자: '경성대ㆍ부경대' vs '경성대부경대'
  - 축약:      '국제금융센터ㆍ부산은행' vs '국제금융센터' vs '국제금융센터부산은행'
               '반여농산물시장' vs '반여농산물' vs '반여'
               '부산대양산캠퍼스' vs '부산대양산'
  - 역 접미:   '부산역' vs 마스터의 '부산'
  - 별칭:      '미남광장' vs '미남'
  - 줄바꿈:    '다대포\\n해수욕장', '국제금융\\n부산은행'
"""

from __future__ import annotations

import re
import unicodedata

# 마스터에 실재하는 역명으로 수렴시키는 명시적 별칭.
# 정규화만으로 도달하지 못하는(글자가 실제로 다른) 경우만 등재한다.
EXPLICIT_ALIASES: dict[str, str] = {
    "부산역": "부산",
    "경성대부경대": "경성대ㆍ부경대",
    "국제금융센터": "국제금융센터ㆍ부산은행",
    "국제금융센터부산은행": "국제금융센터ㆍ부산은행",
    "국제금융부산은행": "국제금융센터ㆍ부산은행",
    "반여": "반여농산물시장",
    "반여농산물": "반여농산물시장",
    "부산대양산": "부산대양산캠퍼스",
    "미남광장": "미남",
}

# 호선 접두가 붙는 역명(환승으로 역명이 중복되는 역)
DUPLICATED_NAMES: frozenset[str] = frozenset(
    {"서면", "연산", "동래", "수영", "덕천", "미남"}
)

_LINE_PREFIX = re.compile(r"^([1-4])\s*(.+)$")
_STRIP_CHARS = re.compile(r"[\s·・ㆍ•]+")  # 공백·중점류 전부 제거


def _base_normalize(raw: str) -> str:
    """유니코드/공백/중점 수준의 기계적 정규화."""
    s = unicodedata.normalize("NFC", str(raw)).strip()
    return _STRIP_CHARS.sub("", s)


def split_line_prefix(raw: str) -> tuple[int | None, str]:
    """'2서면' → (2, '서면'). 접두가 없으면 (None, 원본).

    '1호선' 같은 문자열이 아니라 역명에 붙은 한 자리 호선 접두만 처리한다.
    """
    s = _base_normalize(raw)
    m = _LINE_PREFIX.match(s)
    if m and m.group(2) in DUPLICATED_NAMES:
        return int(m.group(1)), m.group(2)
    return None, s


def canonical_name(raw: str) -> str:
    """어떤 표기든 마스터 역명으로 수렴시킨다."""
    _, name = split_line_prefix(raw)
    # 별칭 조회는 중점 제거본 기준으로 한 뒤 마스터 표기로 되돌린다.
    return EXPLICIT_ALIASES.get(name, name)


def match_key(raw: str) -> str:
    """조인 전용 키. 마스터 표기의 중점까지 제거한 형태."""
    return _base_normalize(canonical_name(raw))


def parse_line_no(raw) -> int | None:
    """'1호선' / 1 / '1' → 1. 그 외(동해선·경전철 등)는 None."""
    if raw is None:
        return None
    s = unicodedata.normalize("NFC", str(raw)).strip()
    m = re.match(r"^([1-4])(호선)?$", s)
    return int(m.group(1)) if m else None
