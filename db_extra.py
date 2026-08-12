# -*- coding: utf-8 -*-
"""
db_extra.py
─────────────────────────────────────────────────────────────
고도화 기능이 쓰는 부가 시트 전용 입출력 계층

  세트구성 · 수량산출 · 공정계획 · 공휴일 · 변경사유

왜 별도 모듈인가
  기존 db_manager.py 를 직접 고치면 이미 잘 돌아가는 코드를 건드려야 하고,
  나중에 db_manager 를 다시 받으면 추가분이 사라진다.
  이 파일만 추가하면 db_manager.py 는 한 줄도 수정할 필요가 없다.

의존
  db_manager 의 공개 API(get_sheet / Result)만 쓴다.
  잠금·원자적 교체는 db_manager 에 있으면 그것을 쓰고, 없으면 이 파일이 자체 구현한다.
  (저장소 버전이 달라도 동작하도록 방어)
"""

from __future__ import annotations

import datetime as _dt
import time

import pandas as pd
import streamlit as st

import config
import db_manager as db
import logic_boq as boq
import logic_change as chg
import logic_schedule as sch
import logic_takeoff as tko

log = config.get_logger("db_extra")

API_CHUNK = 5000
TMP_PREFIX = "_임시_"
RETIRED_PREFIX = "_교체중_"
ERR_KEY = "_extra_load_errors"

# 시트명 → 표준 컬럼
SHEETS: dict[str, list] = {
    boq.SET_SHEET:      boq.SET_COLUMNS,
    tko.TAKEOFF_SHEET:  tko.TAKEOFF_COLUMNS,
    sch.SCHEDULE_SHEET: sch.SCHEDULE_COLUMNS,
    sch.HOLIDAY_SHEET:  sch.HOLIDAY_COLUMNS,
    chg.REASON_SHEET:   chg.REASON_COLUMNS,
}


# ═══════════════════════════════════════════════════════════
# 0. db_manager 연동 (버전 차이 방어)
# ═══════════════════════════════════════════════════════════
Result = db.Result


def _record_error(message) -> None:
    """오류 사유를 세션에 모아 화면이 한 번 표시하고 비운다."""
    if not message:
        return
    # db_manager 의 수집함을 함께 쓰면 화면 표시 지점이 하나로 모인다
    recorder = getattr(db, "_record_error", None)
    if callable(recorder):
        try:
            recorder(message)
            return
        except Exception:
            log.exception("db_manager._record_error 위임 실패")
    bucket = st.session_state.setdefault(ERR_KEY, [])
    if message not in bucket:
        bucket.append(message)


def consume_load_errors() -> list:
    """이 모듈이 자체 수집한 오류를 반환하고 비운다."""
    return st.session_state.pop(ERR_KEY, [])


def _fail(exc: Exception, action: str):
    log.exception("%s 실패", action)
    return Result.failure(f"{action} 실패: {type(exc).__name__} - {exc}")


def _acquire_lock(doc, owner):
    fn = getattr(db, "acquire_write_lock", None)
    if callable(fn):
        return fn(doc, owner)
    return Result.success("잠금 미지원 버전 — 건너뜀")


def _release_lock(doc, owner) -> None:
    fn = getattr(db, "release_write_lock", None)
    if callable(fn):
        try:
            fn(doc, owner)
        except Exception:
            log.exception("잠금 해제 실패")


def _atomic_replace(doc, sheet_name: str, values: list) -> None:
    """시트를 원자적으로 교체한다. db_manager 구현이 있으면 그것을 사용."""
    fn = getattr(db, "_atomic_replace_worksheet", None)
    if callable(fn):
        fn(doc, sheet_name, values)
        return

    # 자체 구현 (임시 시트 기록 → 검증 → 이름 교체 → 구본 삭제)
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    rows = max(len(values) + 100, 200)
    cols = max((len(values[0]) if values else 1) + 2, 8)
    tmp = doc.add_worksheet(title=f"{TMP_PREFIX}{stamp}_{sheet_name}",
                            rows=str(rows), cols=str(cols))
    try:
        if values:
            for i in range(0, len(values), API_CHUNK):
                tmp.update(values[i:i + API_CHUNK], f"A{i + 1}",
                           value_input_option="USER_ENTERED")
                if len(values) > API_CHUNK:
                    time.sleep(1)
        if len(tmp.get_all_values()) < len(values):
            raise RuntimeError(f"기록 검증 실패: 기대 {len(values)}행")

        original = doc.worksheet(sheet_name)
        original.update_title(f"{RETIRED_PREFIX}{stamp}_{sheet_name}")
        try:
            tmp.update_title(sheet_name)
        except Exception:
            original.update_title(sheet_name)      # 롤백
            raise
        try:
            doc.del_worksheet(original)
        except Exception:
            log.exception("구 시트 삭제 실패 (데이터는 정상 교체됨)")
    except Exception:
        try:
            doc.del_worksheet(tmp)
        except Exception:
            log.exception("임시 시트 정리 실패")
        raise


# ═══════════════════════════════════════════════════════════
# 1. 읽기
# ═══════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def _read_sheet(sheet_name: str, columns: tuple):
    """(DataFrame, 오류메시지). 시트가 없으면 빈 표 + 오류 없음(정상)."""
    try:
        worksheet = db.get_sheet().worksheet(sheet_name)
        records = worksheet.get_all_records()
        if not records:
            return pd.DataFrame(columns=list(columns)), None
        return pd.DataFrame(records), None
    except Exception as exc:
        # gspread 버전에 따라 예외 클래스명이 달라 이름으로 판별한다
        if type(exc).__name__ == "WorksheetNotFound":
            return pd.DataFrame(columns=list(columns)), None
        log.exception("%s 시트 읽기 실패", sheet_name)
        return (pd.DataFrame(columns=list(columns)),
                f"'{sheet_name}' 읽기 오류: {type(exc).__name__} - {exc}")


def load(sheet_name: str) -> pd.DataFrame:
    if sheet_name not in SHEETS:
        raise KeyError(f"알 수 없는 시트: {sheet_name}")
    df, err = _read_sheet(sheet_name, tuple(SHEETS[sheet_name]))
    _record_error(err)
    return df


def get_set_sheet() -> pd.DataFrame:
    """세트구성 (일위대가)"""
    return load(boq.SET_SHEET)


def get_takeoff_sheet() -> pd.DataFrame:
    """수량산출"""
    return load(tko.TAKEOFF_SHEET)


def get_schedule_sheet() -> pd.DataFrame:
    """공정계획"""
    return load(sch.SCHEDULE_SHEET)


def get_holiday_sheet() -> pd.DataFrame:
    """공휴일 (비어 있으면 기본값 사용)"""
    return load(sch.HOLIDAY_SHEET)


def get_reason_sheet() -> pd.DataFrame:
    """변경사유"""
    return load(chg.REASON_SHEET)


def exists(sheet_name: str) -> bool:
    """시트에 데이터가 1행이라도 있는지."""
    try:
        return not load(sheet_name).empty
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════
# 2. 쓰기
# ═══════════════════════════════════════════════════════════
def save(sheet_name: str, df: pd.DataFrame):
    """부가 시트를 원자적으로 교체 저장한다."""
    if sheet_name not in SHEETS:
        return Result.failure(f"알 수 없는 시트: {sheet_name}", code="invalid")

    owner = st.session_state.get("_session_id", "unknown")
    doc = None
    try:
        doc = db.get_sheet()
        lock = _acquire_lock(doc, owner)
        if not lock:
            return lock

        columns = SHEETS[sheet_name]
        payload = df.copy() if df is not None else pd.DataFrame()
        for column in columns:
            if column not in payload.columns:
                payload[column] = ""
        payload = payload[columns]

        # 완전히 빈 행 제거 (data_editor 가 남기는 빈 줄)
        mask = payload.astype(str).apply(
            lambda row: any(v.strip() not in ("", "nan", "None") for v in row), axis=1)
        payload = payload[mask] if len(payload) else payload

        try:
            doc.worksheet(sheet_name)
        except Exception as exc:
            if type(exc).__name__ != "WorksheetNotFound":
                raise
            doc.add_worksheet(title=sheet_name, rows="2000",
                              cols=str(len(columns) + 2)).append_row(columns)

        values = [list(columns)] + payload.fillna("").astype(object).values.tolist()
        _atomic_replace(doc, sheet_name, values)
        _read_sheet.clear()
        log.info("%s 저장: %d행", sheet_name, len(payload))
        return Result.success(f"{sheet_name} 저장 완료 ({len(payload):,}행)")
    except Exception as exc:
        return _fail(exc, f"{sheet_name} 저장")
    finally:
        if doc is not None:
            _release_lock(doc, owner)


def ensure_sheets():
    """부가 시트가 없으면 헤더만 넣어 생성한다. (최초 1회)"""
    if st.session_state.get("_extra_sheets_ready"):
        return Result.success("이미 준비됨")
    try:
        doc = db.get_sheet()
        existing = [w.title for w in doc.worksheets()]
        created = []
        for sheet_name, columns in SHEETS.items():
            if sheet_name not in existing:
                doc.add_worksheet(title=sheet_name, rows="2000",
                                  cols=str(len(columns) + 2)).append_row(columns)
                created.append(sheet_name)
        st.session_state["_extra_sheets_ready"] = True
        if created:
            _read_sheet.clear()
            log.info("부가 시트 생성: %s", ", ".join(created))
            return Result.success("시트 생성: " + ", ".join(created), data=created)
        return Result.success("부가 시트 확인 완료")
    except Exception as exc:
        return _fail(exc, "부가 시트 준비")


def clear_cache() -> None:
    """저장 직후 화면을 새 데이터로 갱신할 때 사용."""
    _read_sheet.clear()
