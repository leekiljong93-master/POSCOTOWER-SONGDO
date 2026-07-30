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

import pandas as pd

# 금액 문자열에서 제거할 문자 (콤마, 공백, 통화기호)
_MONEY_NOISE = r"[,\s₩원\u00a0]"

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
GUBUN_TO_SHEET = {v: k for k, v in SHEET_TO_GUBUN.items()}

MASTER_SHEET_NAMES = list(SHEET_TO_GUBUN.keys())
GUBUN_OPTIONS = list(SHEET_TO_GUBUN.values())

# 원가계산서(갑지) 집계 비목. '세트'는 아래 SET_COST_TARGET 비목으로 합산된다.
COST_GROUPS = ("자재", "노무", "장비")

# '세트' 품목을 원가계산 시 어느 비목으로 집계할지 결정한다.
# (과거 버전은 세트를 '자재'로 저장했으므로 기존 산출액과 동일하게 유지하려면 '자재')
SET_COST_TARGET = "자재"

# '구분' → 원가 집계 비목
GUBUN_TO_COST_GROUP = {
    "자재": "자재",
    "노무": "노무",
    "장비": "장비",
    "세트": SET_COST_TARGET,
}

# 사람이 손으로 입력하거나 외부 CSV에서 흘러 들어오는 이형 표기 흡수용
GUBUN_ALIASES = {
    "자재": "자재", "자재비": "자재", "재료": "자재", "재료비": "자재",
    "직접재료비": "자재", "material": "자재",
    "노무": "노무", "노무비": "노무", "인건": "노무", "인건비": "노무",
    "직접노무비": "노무", "labor": "노무",
    "장비": "장비", "장비비": "장비", "기계": "장비", "기계경비": "장비",
    "equipment": "장비",
    "세트": "세트", "세트품": "세트", "일위대가": "세트", "set": "세트",
}

# ═══════════════════════════════════════════════════════════
# 2. 데이터 스키마
# ═══════════════════════════════════════════════════════════
ESTIMATE_COLUMNS = ["구분", "공종명", "규격", "단위", "단가", "수량", "합계", "시작일", "종료일"]
ESTIMATE_NUMERIC_COLUMNS = ["단가", "수량", "합계"]
ESTIMATE_DATE_COLUMNS = ["시작일", "종료일"]
# 과거 버전이 남겨 놓은 찌꺼기 컬럼 (읽는 즉시 제거)
ESTIMATE_JUNK_COLUMNS = ["선택", "level_0", "index", "NO."]

MASTER_BASE_COLUMNS = ["item_name", "spec", "unit", "unit_price", "source"]
# [패치 ②-연계] 읽을 때 버려서 저장 시 유실되던 부가 컬럼을 보존한다.
MASTER_OPTIONAL_COLUMNS = ["category_large", "category_mid", "note"]
MASTER_ALL_COLUMNS = MASTER_BASE_COLUMNS + MASTER_OPTIONAL_COLUMNS

UNIT_OPTIONS = ["일", "시간", "식", "m3", "m2", "m", "ton", "kg", "EA", "인", "대", "조", "포", "장", "회"]

PROJECT_SHEET = "프로젝트저장소"
PROJECT_SHEET_HEADER = ["project_name", "date", "data_json"]

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

# 산업안전보건관리비 계상 제외 기준 금액 (총 공사금액)
SAFETY_EXEMPTION_LIMIT = 20_000_000

# ═══════════════════════════════════════════════════════════
# 4. [패치 ②] 로깅 초기화
# ═══════════════════════════════════════════════════════════
LOG_LEVEL = os.getenv("PTS_LOG_LEVEL", "INFO").upper()
_LOG_FORMAT = "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s"


def setup_logging() -> logging.Logger:
    """앱 전역 로거를 1회만 구성한다. (stderr 출력 → Streamlit 서버 로그에 남음)"""
    root = logging.getLogger("pts")
    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root.addHandler(handler)
        root.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))
        root.propagate = False
    return root


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(f"pts.{name}")


# ═══════════════════════════════════════════════════════════
# 5. 구분 정규화 헬퍼 (모든 모듈이 이것만 사용한다)
# ═══════════════════════════════════════════════════════════
def normalize_gubun(value) -> str | None:
    """임의 표기('자재비', ' 노무 ', 'Labor') → 표준 '구분'. 인식 불가 시 None."""
    if value is None:
        return None
    key = str(value).strip()
    if not key or key.lower() in ("nan", "none", "-"):
        return None
    return GUBUN_ALIASES.get(key) or GUBUN_ALIASES.get(key.lower())


def normalize_sheet_name(value) -> str | None:
    """임의 표기 → 마스터 시트명('자재비' 등). 인식 불가 시 None."""
    gubun = normalize_gubun(value)
    return GUBUN_TO_SHEET.get(gubun) if gubun else None


def cost_group_of(value) -> str | None:
    """임의 표기 → 원가계산 집계 비목('자재'/'노무'/'장비'). 인식 불가 시 None."""
    gubun = normalize_gubun(value)
    return GUBUN_TO_COST_GROUP.get(gubun) if gubun else None


def to_number_series(values, *, default: float = 0.0) -> pd.Series:
    """금액/수량 문자열을 안전하게 숫자로 변환한다.

    pd.to_numeric 은 '10,000' 같은 콤마 표기를 NaN 으로 만들어 fillna(0) 과 결합되면
    금액이 조용히 0원으로 사라진다. (클라우드 JSON 복원·엑셀 붙여넣기에서 실제 발생)
    이 함수는 콤마·공백·통화기호를 먼저 제거한 뒤 변환한다.
    """
    series = values if isinstance(values, pd.Series) else pd.Series(values)
    if series.empty:
        return pd.Series(dtype="float64")
    if pd.api.types.is_numeric_dtype(series):
        return pd.to_numeric(series, errors="coerce").fillna(default)

    text = series.astype(str).str.replace(_MONEY_NOISE, "", regex=True)
    return pd.to_numeric(text, errors="coerce").fillna(default)


def gubun_series(df: pd.DataFrame) -> pd.Series:
    """DataFrame의 '구분' 열을 표준 구분 Series로 변환 (열이 없으면 빈 Series)."""
    if df is None or df.empty or "구분" not in df.columns:
        return pd.Series(dtype="object")
    return df["구분"].map(normalize_gubun)


def cost_group_series(df: pd.DataFrame) -> pd.Series:
    """DataFrame의 '구분' 열을 원가 집계 비목 Series로 변환."""
    if df is None or df.empty or "구분" not in df.columns:
        return pd.Series(dtype="object")
    return df["구분"].map(cost_group_of)


# ═══════════════════════════════════════════════════════════
# 6. 하위 호환 (구버전 app.py가 config.init_session_state()를 호출하던 경로)
# ═══════════════════════════════════════════════════════════
def init_session_state():
    """[패치 ⑤] 상태 관리는 state_manager로 이관됨. 호환을 위해 위임만 한다."""
    import state_manager  # 순환 import 방지를 위한 지연 import

    state_manager.bootstrap()
