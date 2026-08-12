# -*- coding: utf-8 -*-
"""
config.py
─────────────────────────────────────────────────────────────
전역 상수 · 구분(카테고리) 단일 진실 소스(Single Source of Truth) · 로깅 초기화

[패치 ④] 마스터 시트명(자재비/인건비/장비비/세트)과 내역서 '구분'(자재/노무/장비/세트)이
         서로 다른 체계로 흩어져 있던 문제를 이 파일의 매핑 테이블로 일원화한다.
         이후 어떤 모듈도 '자재', '자재비' 같은 문자열을 직접 하드코딩하지 않는다.
"""

import logging
import os
import re
from numbers import Number

import pandas as pd


# ═══════════════════════════════════════════════════════════
# 0. 앱 메타
# ═══════════════════════════════════════════════════════════

APP_TITLE = "🏗️ 포타송 설계서 작성(by.PI_Lee)"
PAGE_TITLE = "포타송 설계서 작성(Ver.260730)"
PAGE_ICON = "🏗️"


# ═══════════════════════════════════════════════════════════
# 1. [패치 ④] 구분 체계 단일 진실 소스
# ═══════════════════════════════════════════════════════════

# 마스터 시트명 → 내역서 '구분' 표기
SHEET_TO_GUBUN = {
    "자재비": "자재",
    "인건비": "노무",
    "장비비": "장비",
    "세트": "세트",
}

# 내역서 '구분' → 마스터 시트명
GUBUN_TO_SHEET = {
    value: key
    for key, value in SHEET_TO_GUBUN.items()
}

MASTER_SHEET_NAMES = list(SHEET_TO_GUBUN.keys())
GUBUN_OPTIONS = list(SHEET_TO_GUBUN.values())

# 원가계산서(갑지) 집계 비목
# '세트'는 아래 SET_COST_TARGET 비목으로 합산한다.
COST_GROUPS = ("자재", "노무", "장비")

# '세트' 품목을 원가계산 시 어느 비목으로 집계할지 결정한다.
# 과거 버전은 세트를 '자재'로 저장했으므로 기존 산출액과 동일하게 유지한다.
SET_COST_TARGET = "자재"

# '구분' → 원가 집계 비목
GUBUN_TO_COST_GROUP = {
    "자재": "자재",
    "노무": "노무",
    "장비": "장비",
    "세트": SET_COST_TARGET,
}

# 사람이 입력하거나 외부 CSV에서 들어오는 이형 표기 흡수용
GUBUN_ALIASES = {
    "자재": "자재",
    "자재비": "자재",
    "재료": "자재",
    "재료비": "자재",
    "직접재료비": "자재",
    "material": "자재",

    "노무": "노무",
    "노무비": "노무",
    "인건": "노무",
    "인건비": "노무",
    "직접노무비": "노무",
    "labor": "노무",

    "장비": "장비",
    "장비비": "장비",
    "기계": "장비",
    "기계경비": "장비",
    "equipment": "장비",

    "세트": "세트",
    "세트품": "세트",
    "일위대가": "세트",
    "set": "세트",
}


# ═══════════════════════════════════════════════════════════
# 2. 데이터 스키마
# ═══════════════════════════════════════════════════════════

ESTIMATE_COLUMNS = [
    "구분",
    "공종명",
    "규격",
    "단위",
    "단가",
    "수량",
    "합계",
    "시작일",
    "종료일",
]

ESTIMATE_NUMERIC_COLUMNS = [
    "단가",
    "수량",
    "합계",
]

ESTIMATE_DATE_COLUMNS = [
    "시작일",
    "종료일",
]

# 과거 버전이 남겨 놓은 찌꺼기 컬럼
# 데이터를 읽는 즉시 제거한다.
ESTIMATE_JUNK_COLUMNS = [
    "선택",
    "level_0",
    "index",
    "NO.",
]

MASTER_BASE_COLUMNS = [
    "item_name",
    "spec",
    "unit",
    "unit_price",
    "source",
]

# [패치 ②-연계]
# 읽을 때 버려서 저장 시 유실되던 부가 컬럼을 보존한다.
MASTER_OPTIONAL_COLUMNS = [
    "category_large",
    "category_mid",
    "note",
]

MASTER_ALL_COLUMNS = (
    MASTER_BASE_COLUMNS
    + MASTER_OPTIONAL_COLUMNS
)

UNIT_OPTIONS = [
    "일",
    "시간",
    "식",
    "m3",
    "m2",
    "m",
    "ton",
    "kg",
    "EA",
    "인",
    "대",
    "조",
    "포",
    "장",
    "회",
]

PROJECT_SHEET = "프로젝트저장소"

PROJECT_SHEET_HEADER = [
    "project_name",
    "date",
    "data_json",
]


# ═══════════════════════════════════════════════════════════
# 3. 조달청 기준 기본 제비율(%)
# ═══════════════════════════════════════════════════════════

DEFAULT_RATES = {
    "indirect_labor": 14.5,
    "sanjae": 3.7,
    "goyong": 1.15,
    "health": 3.545,
    "elderly": 12.95,
    "pension": 4.5,
    "retire": 2.31,
    "safety": 1.86,
    "env": 0.9,
    "etc_exp": 5.5,
    "general_admin": 5.0,
    "profit": 10.0,
    "tax": 10.0,
}

# 산업안전보건관리비 계상 제외 기준 금액
# 총 공사금액 기준
SAFETY_EXEMPTION_LIMIT = 20_000_000


# ═══════════════════════════════════════════════════════════
# 4. [패치 ②] 로깅 초기화
# ═══════════════════════════════════════════════════════════

LOG_LEVEL = os.getenv(
    "PTS_LOG_LEVEL",
    "INFO",
).upper()

_LOG_FORMAT = (
    "%(asctime)s | "
    "%(levelname)-7s | "
    "%(name)s:%(lineno)d | "
    "%(message)s"
)


def setup_logging() -> logging.Logger:
    """
    앱 전역 로거를 1회만 구성한다.

    stderr 출력으로 Streamlit 서버 로그에 기록한다.
    """
    root = logging.getLogger("pts")

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(_LOG_FORMAT)
        )

        root.addHandler(handler)
        root.setLevel(
            getattr(
                logging,
                LOG_LEVEL,
                logging.INFO,
            )
        )
        root.propagate = False

    return root


def get_logger(name: str) -> logging.Logger:
    """지정한 모듈 이름의 로거를 반환한다."""
    setup_logging()
    return logging.getLogger(f"pts.{name}")


# ═══════════════════════════════════════════════════════════
# 5. 구분 정규화 헬퍼
# ═══════════════════════════════════════════════════════════

def normalize_gubun(value) -> str | None:
    """
    임의 표기를 표준 '구분'으로 변환한다.

    예:
    '자재비' → '자재'
    ' 노무 ' → '노무'
    'Labor'  → '노무'

    인식할 수 없는 값은 None을 반환한다.
    """
    if value is None:
        return None

    key = str(value).strip()

    if not key:
        return None

    if key.lower() in (
        "nan",
        "none",
        "null",
        "<na>",
        "-",
    ):
        return None

    return (
        GUBUN_ALIASES.get(key)
        or GUBUN_ALIASES.get(key.lower())
    )


def normalize_sheet_name(value) -> str | None:
    """
    임의 표기를 마스터 시트명으로 변환한다.

    반환 예:
    자재비, 인건비, 장비비, 세트
    """
    gubun = normalize_gubun(value)

    if gubun is None:
        return None

    return GUBUN_TO_SHEET.get(gubun)


def cost_group_of(value) -> str | None:
    """
    임의 표기를 원가계산 집계 비목으로 변환한다.

    반환 예:
    자재, 노무, 장비
    """
    gubun = normalize_gubun(value)

    if gubun is None:
        return None

    return GUBUN_TO_COST_GROUP.get(gubun)


# ═══════════════════════════════════════════════════════════
# 5-1. 숫자 및 금액 변환 헬퍼
# ═══════════════════════════════════════════════════════════

def to_number_series(series, default=0) -> pd.Series:
    """
    숫자 또는 금액 문자열을 숫자형 Series로 변환한다.

    Parameters
    ----------
    series:
        변환할 Series, 리스트, 튜플 또는 단일 값

    default:
        변환할 수 없는 값에 적용할 기본값
        기본값은 0

    변환 예
    -------
    ₩1,250,000  -> 1250000
    1,250원     -> 1250
    -15,000원   -> -15000
    (15,000)    -> -15000
    12.5%       -> 12.5
    None        -> default
    """

    # Series, 배열, 단일 값을 모두 Series로 통일
    if isinstance(series, pd.Series):
        source_series = series.copy()

    elif isinstance(series, (list, tuple, set)):
        source_series = pd.Series(list(series))

    else:
        source_series = pd.Series([series])

    def clean_number(value):
        """개별 값을 숫자로 변환 가능한 형태로 정리한다."""

        # 결측값 처리
        if value is None:
            return default

        try:
            if pd.isna(value):
                return default
        except (TypeError, ValueError):
            pass

        # bool 처리
        if isinstance(value, bool):
            return int(value)

        # 이미 숫자이면 그대로 반환
        if isinstance(value, Number):
            return value

        text = str(value).strip()

        # 빈 문자열 및 결측값 문자열 처리
        if not text:
            return default

        if text.lower() in {
            "nan",
            "none",
            "null",
            "<na>",
            "-",
        }:
            return default

        # 괄호로 표시된 음수 확인
        # 예: (15,000) -> -15000
        is_parenthesis_negative = (
            text.startswith("(")
            and text.endswith(")")
        )

        # PyArrow 문자열 정규식을 사용하지 않고
        # Python re.sub()로 숫자, 소수점, 음수 기호만 유지
        cleaned = re.sub(
            r"[^0-9.\-]",
            "",
            text,
        )

        if cleaned in {
            "",
            "-",
            ".",
            "-.",
        }:
            return default

        # 음수 기호 위치 정리
        is_negative = "-" in cleaned
        cleaned = cleaned.replace("-", "")

        # 소수점이 여러 개이면 마지막 소수점만 유지
        if cleaned.count(".") > 1:
            parts = cleaned.split(".")
            cleaned = (
                "".join(parts[:-1])
                + "."
                + parts[-1]
            )

        if cleaned in {"", "."}:
            return default

        if is_negative or is_parenthesis_negative:
            cleaned = "-" + cleaned

        return cleaned

    # PyArrow의 str.replace()를 거치지 않고 값별 처리
    cleaned_series = source_series.map(clean_number)

    # 기본값도 숫자형으로 정리
    try:
        numeric_default = float(default)
    except (TypeError, ValueError):
        numeric_default = 0

    # 숫자로 변환
    number_series = pd.to_numeric(
        cleaned_series,
        errors="coerce",
    ).fillna(numeric_default)

    return number_series


def gubun_series(df: pd.DataFrame) -> pd.Series:
    """
    DataFrame의 '구분' 열을 표준 구분 Series로 변환한다.

    DataFrame이 없거나 '구분' 열이 없으면 빈 Series를 반환한다.
    """
    if (
        df is None
        or df.empty
        or "구분" not in df.columns
    ):
        return pd.Series(dtype="object")

    return df["구분"].map(normalize_gubun)


def cost_group_series(df: pd.DataFrame) -> pd.Series:
    """
    DataFrame의 '구분' 열을 원가 집계 비목 Series로 변환한다.
    """
    if (
        df is None
        or df.empty
        or "구분" not in df.columns
    ):
        return pd.Series(dtype="object")

    return df["구분"].map(cost_group_of)


# ═══════════════════════════════════════════════════════════
# 6. 하위 호환
# ═══════════════════════════════════════════════════════════

def init_session_state():
    """
    [패치 ⑤]

    상태 관리는 state_manager로 이관되었다.
    구버전 app.py 호환을 위해 위임만 한다.
    """
    # 순환 import 방지를 위한 지연 import
    import state_manager

    state_manager.bootstrap()