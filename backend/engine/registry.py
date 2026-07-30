# -*- coding: utf-8 -*-
"""정규화된 역 레지스트리.

발제 데이터 5종을 역번호를 정규 키로 하나의 조회 가능한 객체 그래프로 합친다.
엔진의 모든 계산은 여기서 나온 Station / LockerSupply / StationFacility 만 본다.

원본 데이터 보정 사항
  - #1 마스터의 '위도'/'경도' 컬럼은 값이 서로 뒤바뀌어 있다.
    (위도 컬럼에 128.x=경도, 경도 컬럼에 35.x=위도). #3.3 의 '역 위도/역 경도'와
    대조해 확인했고, 여기서 바로잡아 싣는다.
  - #2 승하차에는 3호선 수영(301)·4호선 미남(401)이 없다. 환승역 승하차가
    상대 노선 코드에 합산돼 있기 때문으로, 수요 조회 시 형제 코드로 폴백한다.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from functools import cached_property, lru_cache

import pandas as pd

from . import datasets, naming

# 보관함 규격 서열. 작은 짐은 큰 칸에 들어가지만 그 역은 아니다.
LOCKER_SIZES: tuple[str, ...] = ("소형", "중형", "대형", "특대형")
_SIZE_RANK = {s: i for i, s in enumerate(LOCKER_SIZES)}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@dataclass(frozen=True)
class LockerSupply:
    """한 역의 물품보관함 공급. 같은 역에 여러 대가 있으면 합산된다."""

    counts: dict[str, int]           # 규격 → 칸 수
    price_per_3h: dict[str, int]     # 규격 → 3시간당 요금(원)
    operators: tuple[str, ...]
    locations: tuple[str, ...]

    def capacity_for(self, min_size: str) -> int:
        """min_size 이상 규격의 총 칸 수. 큰 칸은 작은 짐을 수용한다."""
        floor = _SIZE_RANK[min_size]
        return sum(c for s, c in self.counts.items() if _SIZE_RANK[s] >= floor)

    def cheapest_fit(self, min_size: str) -> tuple[str, int] | None:
        """min_size 이상 중 칸이 실재하는 가장 싼 규격."""
        candidates = [
            (s, self.price_per_3h.get(s))
            for s in LOCKER_SIZES
            if _SIZE_RANK[s] >= _SIZE_RANK[min_size] and self.counts.get(s, 0) > 0
        ]
        candidates = [(s, p) for s, p in candidates if p is not None]
        if not candidates:
            return None
        return min(candidates, key=lambda x: x[1])


@dataclass(frozen=True)
class StationFacility:
    """캐리어 동반 이동 난이도를 결정하는 물리 조건 (#3 시리즈)."""

    elevator_count: int = 0
    elevator_running: int = 0
    escalator_count: int = 0
    escalator_running: int = 0
    alt_route_mean_complexity: float | None = None   # #3.3 경로복잡도 점수 1~10
    alt_route_max_complexity: float | None = None
    alt_route_blocked: int = 0                       # '이동 불가' 경로 수
    platform_curved_ratio: float = 0.0               # #3.4 곡선/(완화)곡선 비율
    platform_wide_gap_ratio: float = 0.0             # 연단간격 '넓음' 비율
    platform_type: str | None = None                 # 상대식 / 섬식

    @property
    def has_elevator(self) -> bool:
        return self.elevator_running > 0


@dataclass(frozen=True)
class Station:
    code: int
    line: int
    name: str
    lat: float
    lon: float
    sub_name: str | None = None
    transfer_lines: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return f"{self.line}호선 {self.name}"

    @property
    def is_transfer(self) -> bool:
        return bool(self.transfer_lines)


class StationRegistry:
    """통합 조회 진입점."""

    # 역간 표정 소요시간(분). 부산 도시철도 평균 역간 거리·표정속도 기준 가정치.
    SECONDS_PER_HOP = 120
    TRANSFER_PENALTY_SEC = 300

    def __init__(self) -> None:
        self._stations: dict[int, Station] = {}
        self._by_name: dict[str, list[int]] = {}
        self._by_line_name: dict[tuple[int, str], int] = {}
        self._lockers: dict[int, LockerSupply] = {}
        self._facilities: dict[int, StationFacility] = {}
        self._build_stations()
        self._build_lockers()
        self._build_facilities()

    # ── 구축 ────────────────────────────────────────────────────────
    def _build_stations(self) -> None:
        df = datasets.load_station_master()
        for row in df.itertuples(index=False):
            code = int(getattr(row, "역번호"))
            line = naming.parse_line_no(getattr(row, "호선명"))
            if line is None:
                continue
            name = naming.canonical_name(getattr(row, "역명"))
            transfers = getattr(row, "환승노선명")
            sub = getattr(row, "부역명")
            self._stations[code] = Station(
                code=code,
                line=line,
                name=name,
                # 원본 컬럼이 뒤바뀌어 있어 여기서 바로잡는다.
                lat=float(getattr(row, "경도")),
                lon=float(getattr(row, "위도")),
                sub_name=None if pd.isna(sub) else str(sub).strip(),
                transfer_lines=() if pd.isna(transfers) else tuple(
                    t.strip() for t in str(transfers).split(",") if t.strip()
                ),
            )
            self._by_name.setdefault(naming.match_key(name), []).append(code)
            self._by_line_name[(line, naming.match_key(name))] = code

    def _build_lockers(self) -> None:
        df = datasets.load_lockers()
        acc: dict[int, dict] = {}
        for _, row in df.iterrows():
            line = naming.parse_line_no(row["호선"])
            code = self.resolve(row["역명"], line)
            if code is None:
                continue
            slot = acc.setdefault(
                code,
                {"counts": {}, "price": {}, "ops": [], "locs": []},
            )
            for size in LOCKER_SIZES:
                n = pd.to_numeric(row[f"{size}(개수)"], errors="coerce")
                n = 0 if pd.isna(n) else int(n)
                slot["counts"][size] = slot["counts"].get(size, 0) + n
            slot["price"].update(_parse_locker_price(row["이용요금"]))
            slot["ops"].append(str(row["운영사"]).strip())
            slot["locs"].append(str(row["상세위치"]).strip())

        for code, slot in acc.items():
            self._lockers[code] = LockerSupply(
                counts=slot["counts"],
                price_per_3h=slot["price"],
                operators=tuple(dict.fromkeys(slot["ops"])),
                locations=tuple(slot["locs"]),
            )

    def _build_facilities(self) -> None:
        elv = self._agg_lift(datasets.load_elevators(), "엘리베이터")
        esc = self._agg_lift(datasets.load_escalators(), "에스컬레이터")
        alt = self._agg_alt_routes(datasets.load_alt_routes())
        plat = self._agg_platforms(datasets.load_platforms())

        for code in self._stations:
            e = elv.get(code, (0, 0))
            s = esc.get(code, (0, 0))
            a = alt.get(code, {})
            p = plat.get(code, {})
            self._facilities[code] = StationFacility(
                elevator_count=e[0],
                elevator_running=e[1],
                escalator_count=s[0],
                escalator_running=s[1],
                alt_route_mean_complexity=a.get("mean"),
                alt_route_max_complexity=a.get("max"),
                alt_route_blocked=a.get("blocked", 0),
                platform_curved_ratio=p.get("curved", 0.0),
                platform_wide_gap_ratio=p.get("wide_gap", 0.0),
                platform_type=a.get("platform_type"),
            )

    def _agg_lift(self, df: pd.DataFrame, kind: str) -> dict[int, tuple[int, int]]:
        """(총 대수, 운행 중 대수). 컬럼명에 공백이 있어 iterrows 로 접근한다."""
        out: dict[int, list[int]] = {}
        for _, row in df.iterrows():
            line = naming.parse_line_no(row["호선명"])
            code = self.resolve(row["역명"], line)
            if code is None:
                continue
            slot = out.setdefault(code, [0, 0])
            slot[0] += 1
            if str(row["승강기 상태"]).strip() == "운행":
                slot[1] += 1
        return {k: (v[0], v[1]) for k, v in out.items()}

    def _agg_alt_routes(self, df: pd.DataFrame) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for code, g in df.groupby("역번호"):
            code = int(code)
            if code not in self._stations:
                continue
            scores = pd.to_numeric(g["경로복잡도 점수"], errors="coerce").dropna()
            ptypes = g["승강장 유형"].dropna().unique()
            out[code] = {
                "mean": float(scores.mean()) if len(scores) else None,
                "max": float(scores.max()) if len(scores) else None,
                "blocked": int((g["경로 이용 가능 여부"].astype(str).str.strip() == "N").sum()),
                "platform_type": str(ptypes[0]) if len(ptypes) else None,
            }
        return out

    def _agg_platforms(self, df: pd.DataFrame) -> dict[int, dict]:
        out: dict[int, dict] = {}
        for code, g in df.groupby("역번호"):
            code = int(code)
            if code not in self._stations:
                continue
            shape = g["승강장선형"].astype(str).str.strip()
            gap = g["연단간격"].astype(str).str.strip()
            n = max(len(g), 1)
            out[code] = {
                "curved": float(shape.str.contains("곡선").sum()) / n,
                "wide_gap": float((gap == "넓음").sum()) / n,
            }
        return out

    # ── 조회 ────────────────────────────────────────────────────────
    def resolve(self, name, line: int | None = None) -> int | None:
        """(역명, 호선) → 역번호. 호선을 모르면 유일할 때만 성공한다."""
        if name is None or (isinstance(name, float) and pd.isna(name)):
            return None
        prefix_line, _ = naming.split_line_prefix(str(name))
        line = prefix_line if prefix_line is not None else line
        key = naming.match_key(str(name))
        if line is not None:
            hit = self._by_line_name.get((line, key))
            if hit is not None:
                return hit
        codes = self._by_name.get(key, [])
        # 환승역은 이용자에겐 하나의 역사(驛舍)다. 호선을 지정하지 않았으면
        # 대표(최소 코드) 승강장을 돌려주고, 공급 조회는 complex 단위로 합산한다.
        return min(codes) if codes else None

    def complex_codes(self, code: int) -> list[int]:
        """같은 역사에 속한 모든 승강장 코드. 환승역이면 2개 이상."""
        return sorted([code, *self.siblings(code)])

    def locker_complex(self, code: int) -> LockerSupply | None:
        """역사 단위 합산 보관함 공급. 서면처럼 1·2호선에 각각 있는 경우를 합친다."""
        parts = [s for c in self.complex_codes(code) if (s := self._lockers.get(c))]
        if not parts:
            return None
        if len(parts) == 1:
            return parts[0]
        counts: dict[str, int] = {}
        price: dict[str, int] = {}
        for p in parts:
            for size, n in p.counts.items():
                counts[size] = counts.get(size, 0) + n
            for size, amount in p.price_per_3h.items():
                price[size] = min(price.get(size, amount), amount)
        return LockerSupply(
            counts=counts,
            price_per_3h=price,
            operators=tuple(dict.fromkeys(o for p in parts for o in p.operators)),
            locations=tuple(loc for p in parts for loc in p.locations),
        )

    def station(self, code: int) -> Station:
        return self._stations[code]

    def get(self, name, line: int | None = None) -> Station | None:
        code = self.resolve(name, line)
        return self._stations[code] if code is not None else None

    @property
    def stations(self) -> dict[int, Station]:
        return dict(self._stations)

    def locker(self, code: int) -> LockerSupply | None:
        return self._lockers.get(code)

    def facility(self, code: int) -> StationFacility:
        return self._facilities.get(code, StationFacility())

    def siblings(self, code: int) -> list[int]:
        """같은 역명의 다른 노선 승강장(환승 쌍둥이)."""
        st = self._stations[code]
        return [c for c in self._by_name.get(naming.match_key(st.name), []) if c != code]

    # ── 인접 그래프 ─────────────────────────────────────────────────
    @cached_property
    def _adjacency(self) -> dict[int, set[int]]:
        """역번호 ±1(동일 노선) = 물리적 인접역. 환승 쌍둥이도 0홉으로 연결."""
        adj: dict[int, set[int]] = {c: set() for c in self._stations}
        for code, st in self._stations.items():
            for nb in (code - 1, code + 1):
                other = self._stations.get(nb)
                if other is not None and other.line == st.line:
                    adj[code].add(nb)
            for sib in self.siblings(code):
                adj[code].add(sib)
        return adj

    def adjacent(self, code: int) -> set[int]:
        """직접 연결된 역들. 같은 노선 인접역 + 환승 쌍둥이."""
        return set(self._adjacency[code])

    def neighbors_within(self, code: int, hops: int) -> dict[int, int]:
        """code 로부터 hops 정거장 이내의 역 → 홉 수. 환승 쌍둥이는 0홉."""
        seen = {code: 0}
        frontier = [code]
        for _ in range(hops):
            nxt = []
            for cur in frontier:
                for nb in self._adjacency[cur]:
                    step = 0 if self._stations[nb].name == self._stations[cur].name else 1
                    d = seen[cur] + step
                    if d <= hops and (nb not in seen or d < seen[nb]):
                        seen[nb] = d
                        nxt.append(nb)
            frontier = nxt
            if not frontier:
                break
        return seen

    def hop_travel_seconds(self, hops: int, transfers: int = 0) -> int:
        return hops * self.SECONDS_PER_HOP + transfers * self.TRANSFER_PENALTY_SEC

    def walk_seconds(self, a: int, b: int, kmph: float = 3.2) -> int:
        """캐리어 동반 도보 속도 3.2km/h 가정."""
        sa, sb = self._stations[a], self._stations[b]
        km = haversine_km(sa.lat, sa.lon, sb.lat, sb.lon)
        return int(km / kmph * 3600)


_PRICE_TOKEN = re.compile(r"(특대|대|중|소)\s*[:：]?\s*([\d,]+)\s*원")
_TOKEN_TO_SIZE = {"소": "소형", "중": "중형", "대": "대형", "특대": "특대형"}


def _parse_locker_price(raw) -> dict[str, int]:
    """'특대: 6,000원 / 대:4,000원 / 중: 3,000원 / 소: 2,000원(3시간당)' 파싱.

    '특대'가 '대'보다 먼저 매칭되도록 정규식 대안 순서를 잡아 뒀다.
    """
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    out: dict[str, int] = {}
    for token, amount in _PRICE_TOKEN.findall(str(raw)):
        out[_TOKEN_TO_SIZE[token]] = int(amount.replace(",", ""))
    return out


@lru_cache(maxsize=1)
def get_registry() -> StationRegistry:
    return StationRegistry()
