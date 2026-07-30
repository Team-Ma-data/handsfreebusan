# -*- coding: utf-8 -*-
"""발제사 원본 파일 로더.

원본은 읽기 전용으로 취급한다. 여기서는 파일 탐색과 인코딩 처리만 하고,
의미 있는 정규화는 registry.py가 담당한다.

주의사항 두 가지:
  1) 파일/폴더명이 NFD(자소 분리) 형태로 저장돼 있어 문자열 비교 시
     NFC 정규화가 필요하다. 그래서 경로를 하드코딩하지 않고 부분 문자열로 찾는다.
  2) 전 CSV가 CP949 인코딩이다.
"""

from __future__ import annotations

import os
import unicodedata
from functools import lru_cache
from pathlib import Path

import pandas as pd

ENCODING = "cp949"

# engine/ 의 부모 = 프로젝트 루트, 그 아래 '발제사 데이터'
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = PROJECT_ROOT / "발제사 데이터"
CACHE_DIR = PROJECT_ROOT / "engine" / "cache"


@lru_cache(maxsize=1)
def _file_index() -> dict[str, str]:
    """NFC 정규화된 파일명 → 실제 경로."""
    index: dict[str, str] = {}
    for root, _dirs, files in os.walk(DATA_ROOT):
        for f in files:
            index[unicodedata.normalize("NFC", f)] = os.path.join(root, f)
    if not index:
        raise FileNotFoundError(f"발제사 데이터를 찾을 수 없습니다: {DATA_ROOT}")
    return index


def _squash(s: str) -> str:
    """공백을 무시한 비교용 키.

    원본 파일명에 '승강장 간 격및 곡선구간'처럼 띄어쓰기가 어긋난 것이 있어
    문자열 그대로 비교하면 못 찾는다. 원본을 고치지 않고 여기서 흡수한다.
    """
    return "".join(unicodedata.normalize("NFC", s).split())


def resolve(fragment: str) -> str:
    """파일명 일부로 실제 경로를 찾는다(공백 무시)."""
    frag = _squash(fragment)
    hits = [p for name, p in _file_index().items() if frag in _squash(name)]
    if not hits:
        raise FileNotFoundError(f"'{fragment}' 에 해당하는 데이터 파일이 없습니다")
    if len(hits) > 1:
        raise ValueError(f"'{fragment}' 가 여러 파일에 매칭됩니다: {hits}")
    return hits[0]


def _csv(fragment: str, **kwargs) -> pd.DataFrame:
    return pd.read_csv(resolve(fragment), encoding=ENCODING, **kwargs)


# ── #1 역사 정보 마스터 ─────────────────────────────────────────────
def load_station_master() -> pd.DataFrame:
    return _csv("1. 역사 정보 마스터")


# ── #2 시간대별 승하차 인원 (409k행, 48MB) ──────────────────────────
def load_ridership(**kwargs) -> pd.DataFrame:
    return _csv("2. 시간대별", low_memory=False, **kwargs)


# ── #3 역사별 이동 편의시설 ─────────────────────────────────────────
def load_elevators() -> pd.DataFrame:
    return _csv("1. 역사별 엘리베이터 정보")


def load_escalators() -> pd.DataFrame:
    return _csv("2. 역사별 에스컬레이터 정보")


def load_alt_routes() -> pd.DataFrame:
    return _csv("3. 엘리베이터 고장 시 대체 이동 경로")


def load_platforms() -> pd.DataFrame:
    return _csv("4. 승강장 간격 및 곡선구간 정보")


# ── #4 역사별 편의시설 ──────────────────────────────────────────────
def load_lockers() -> pd.DataFrame:
    return _csv("1. 역사별 물품보관함 현황 정보")


def load_atms() -> pd.DataFrame:
    return _csv("2. 역사별 ATM 설치 현황 정보")


def load_chargers() -> pd.DataFrame:
    return _csv("3. 역사별 핸드폰 충전설비 현황 정보")


def load_kiosks() -> pd.DataFrame:
    return _csv("4. 교통약자 네비게이션 키오스크")


# ── #5 주요거점·권역별 짐배송 이동 흐름 (xlsx) ──────────────────────
def load_luggage_flow() -> dict[str, pd.DataFrame]:
    """방향별 OD 비율 시트를 그대로 돌려준다.

    시트 구조: 3행이 헤더(권역), 4~6행이 거점, 마지막 열이 행 합계.
    파싱은 registry.py 의 build_coverage_matrix 가 담당한다.
    """
    path = resolve("5. 주요거점")
    xl = pd.ExcelFile(path)
    return {name: xl.parse(name, header=None) for name in xl.sheet_names}
