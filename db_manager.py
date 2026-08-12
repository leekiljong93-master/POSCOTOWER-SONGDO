# -*- coding: utf-8 -*-
"""
db_manager.py
─────────────────────────────────────────────────────────────
Google Sheets 영속성 계층

[패치 ①] clear() → append_rows() 2단계 덮어쓰기 제거
          · 임시 시트에 전량 기록 → 검증 → 원본 이름 교체(rename swap) → 구본 삭제
          · 중간 실패 시 원본이 남아 있으므로 마스터가 비는 사고가 발생하지 않는다.
          · 다중 사용자 동시 저장 방지를 위한 권고적 쓰기 잠금(advisory lock) 추가
[패치 ②] except Exception: pass 형태의 침묵 제거
          · 모든 예외를 logger.exception 으로 기록
          · 읽기 실패는 (DataFrame, error) 로 반환하여 UI가 사유를 표시할 수 있게 함
[패치 ③] 반환 타입 통일
          · 모든 쓰기 함수는 Result 객체 반환 (bool / 문자열 / dict 혼용 폐기)
          · 구버전 호출부 호환을 위해 res["status"], res["message"] 접근도 지원
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

import gspread
import pandas as pd
import streamlit as st
from google.oauth2.service_account import Credentials

import config

log = config.get_logger("db")

BACKUP_PREFIX = "_백업_"
TMP_PREFIX = "_임시_"
RETIRED_PREFIX = "_교체중_"
LOCK_SHEET = "_쓰기잠금"

BACKUP_LIMIT = 10
LOCK_TTL_SEC = 180
API_CHUNK = 5000
ERR_KEY = "_master_load_errors"


# ═══════════════════════════════════════════════════════════
# 0. [패치 ③] 통일 반환 타입
# ═══════════════════════════════════════════════════════════
@dataclass(frozen=True)
class Result:
    """모든 쓰기 작업의 표준 반환 타입.

    사용 예)
        res = db.save_project_to_cloud(...)
        if res:                      # __bool__ 지원
            st.success(res.message)
        else:
            st.error(res.message)
    """

    ok: bool
    message: str = ""
    code: str = ""                      # "", "conflict", "locked", "not_found", "invalid", "error"
    data: Any = None
    meta: dict = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok

    @property
    def status(self) -> str:
        return "success" if self.ok else "error"

    # 구버전 호출부(res["status"] == "success") 호환
    def __getitem__(self, key: str):
        mapping = {"status": self.status, "message": self.message,
                   "code": self.code, "data": self.data}
        if key in mapping:
            return mapping[key]
        raise KeyError(key)

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    @classmethod
    def success(cls, message: str = "", *, data: Any = None, **meta) -> "Result":
        return cls(True, message, "", data, meta)

    @classmethod
    def failure(cls, message: str, *, code: str = "error", data: Any = None, **meta) -> "Result":
        return cls(False, message, code, data, meta)


def _fail_from_exc(exc: Exception, action: str) -> Result:
    """[패치 ②] 예외를 로그에 남기고 사용자용 메시지로 변환."""
    log.exception("%s 실패", action)
    return Result.failure(f"{action} 실패: {type(exc).__name__} - {exc}")


# ═══════════════════════════════════════════════════════════
# 1. 연결
# ═══════════════════════════════════════════════════════════
@st.cache_resource(show_spinner=False)
def get_gsheet_client():
    if os.path.exists("service_account.json"):
        with open("service_account.json", "r", encoding="utf-8") as f:
            creds_json = json.load(f)
        log.info("인증: 로컬 service_account.json 사용")
    else:
        try:
            creds_json = dict(st.secrets["GOOGLE_CREDENTIALS"])
            log.info("인증: Streamlit secrets 사용")
        except Exception:
            log.exception("GOOGLE_CREDENTIALS 로드 실패")
            raise

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return gspread.authorize(creds)


@st.cache_resource(show_spinner=False)
def get_sheet():
    client = get_gsheet_client()
    return client.open_by_url(st.secrets["SPREADSHEET_URL"])


def init_db() -> Result:
    """연결과 필수 워크시트를 준비한다. [패치 ③] Result 반환."""
    if st.session_state.get("_db_initialized"):
        return Result.success("이미 초기화되었습니다.")

    try:
        doc = get_sheet()
        existing = [ws.title for ws in doc.worksheets()]

        for name in config.MASTER_SHEET_NAMES:
            if name not in existing:
                doc.add_worksheet(title=name, rows="1000", cols="12") \
                   .append_row(config.MASTER_ALL_COLUMNS)
                log.info("마스터 시트 생성: %s", name)

        if config.PROJECT_SHEET not in existing:
            doc.add_worksheet(title=config.PROJECT_SHEET, rows="1000", cols="6") \
               .append_row(config.PROJECT_SHEET_HEADER)
            log.info("프로젝트저장소 시트 생성")

        _cleanup_stale_sheets(doc)
        st.session_state["_db_initialized"] = True
        return Result.success("Google Sheets 연결 완료")
    except Exception as exc:
        return _fail_from_exc(exc, "Google Sheets 초기화")


# ═══════════════════════════════════════════════════════════
# 2. [패치 ①] 권고적 쓰기 잠금
# ═══════════════════════════════════════════════════════════
def _lock_ws(doc):
    try:
        return doc.worksheet(LOCK_SHEET)
    except gspread.exceptions.WorksheetNotFound:
        ws = doc.add_worksheet(title=LOCK_SHEET, rows="5", cols="2")
        ws.update([["{}"]], "A1")
        return ws


def acquire_write_lock(doc, owner: str, *, ttl: int = LOCK_TTL_SEC) -> Result:
    """마스터 시트 동시 저장을 막는 권고적 잠금.

    주의: Google Sheets에는 원자적 CAS가 없어 완전한 상호배제는 아니다.
          '두 사람이 같은 순간 저장' 같은 현실적 충돌을 차단하는 수준이다.
    """
    try:
        ws = _lock_ws(doc)
        raw = (ws.acell("A1").value or "").strip()
        holder = json.loads(raw) if raw.startswith("{") else {}

        if holder.get("owner") and holder.get("owner") != owner:
            held_at = holder.get("at", "")
            try:
                elapsed = (_dt.datetime.now() - _dt.datetime.fromisoformat(held_at)).total_seconds()
            except Exception:
                elapsed = ttl + 1
            if elapsed < ttl:
                return Result.failure(
                    f"다른 사용자가 저장 중입니다. {int(ttl - elapsed)}초 후 다시 시도하세요.",
                    code="locked",
                )
            log.warning("만료된 잠금 강제 회수 (owner=%s, %.0fs 경과)", holder.get("owner"), elapsed)

        payload = json.dumps({"owner": owner, "at": _dt.datetime.now().isoformat()},
                             ensure_ascii=False)
        ws.update([[payload]], "A1")
        return Result.success("잠금 획득")
    except Exception as exc:
        # 잠금 실패로 저장 자체를 막지는 않되, 반드시 기록한다.
        log.exception("쓰기 잠금 획득 중 오류")
        return Result.failure(f"잠금 처리 오류: {exc}", code="error")


def release_write_lock(doc, owner: str) -> None:
    try:
        ws = _lock_ws(doc)
        raw = (ws.acell("A1").value or "").strip()
        holder = json.loads(raw) if raw.startswith("{") else {}
        if holder.get("owner") in (owner, None, ""):
            ws.update([["{}"]], "A1")
    except Exception:
        log.exception("쓰기 잠금 해제 실패 (수동 확인 필요)")


# ═══════════════════════════════════════════════════════════
# 3. [패치 ①] 원자적 시트 교체
# ═══════════════════════════════════════════════════════════
def _stamp() -> str:
    return _dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")


def _cleanup_stale_sheets(doc, *, older_than_hours: int = 6) -> None:
    """중단된 작업이 남긴 임시/교체중 시트를 정리한다."""
    threshold = _dt.datetime.now() - _dt.timedelta(hours=older_than_hours)
    for ws in doc.worksheets():
        for prefix in (TMP_PREFIX, RETIRED_PREFIX):
            if not ws.title.startswith(prefix):
                continue
            raw = ws.title[len(prefix):].split("_")
            try:
                created = _dt.datetime.strptime("_".join(raw[:2]), "%Y%m%d_%H%M%S")
            except Exception:
                continue
            if created < threshold:
                try:
                    doc.del_worksheet(ws)
                    log.info("잔여 시트 정리: %s", ws.title)
                except Exception:
                    log.exception("잔여 시트 정리 실패: %s", ws.title)


def _atomic_replace_worksheet(doc, sheet_name: str, values: list[list]) -> None:
    """시트 내용을 원자적으로 교체한다.

    순서: ①임시 시트 생성·전량 기록 ②기록 검증 ③원본 rename(교체중)
          ④임시 → 원본 이름 ⑤교체중 삭제
    ③~④ 사이 실패 시 원본 이름을 되돌려 롤백한다.
    """
    stamp = _stamp()
    n_rows = max(len(values) + 100, 200)
    n_cols = max((len(values[0]) if values else 1) + 2, 8)
    tmp_title = f"{TMP_PREFIX}{stamp}_{sheet_name}"

    tmp = doc.add_worksheet(title=tmp_title, rows=str(n_rows), cols=str(n_cols))
    try:
        # 단일 batch 호출로 기록 (append_rows 반복 → 부분 기록 위험 제거)
        if values:
            for i in range(0, len(values), API_CHUNK):
                chunk = values[i:i + API_CHUNK]
                tmp.update(chunk, f"A{i + 1}", value_input_option="USER_ENTERED")
                if len(values) > API_CHUNK:
                    time.sleep(1)  # 쿼터 보호

        written = len(tmp.get_all_values())
        if written < len(values):
            raise RuntimeError(f"기록 검증 실패: 기대 {len(values)}행 / 실제 {written}행")

        original = doc.worksheet(sheet_name)
        retired_title = f"{RETIRED_PREFIX}{stamp}_{sheet_name}"
        original.update_title(retired_title)
        try:
            tmp.update_title(sheet_name)
        except Exception:
            original.update_title(sheet_name)   # 롤백
            raise

        try:
            doc.del_worksheet(original)
        except Exception:
            # 데이터는 이미 정상 교체 완료. 잔여 시트는 다음 정리 주기에 제거된다.
            log.exception("구 시트 삭제 실패 (잔여: %s)", retired_title)

        log.info("원자적 교체 완료: %s (%d행)", sheet_name, len(values))
    except Exception:
        try:
            doc.del_worksheet(tmp)
        except Exception:
            log.exception("임시 시트 정리 실패: %s", tmp_title)
        raise


# ═══════════════════════════════════════════════════════════
# 4. 백업 / 복구
# ═══════════════════════════════════════════════════════════
def _backup_sheet_name(backup_id: str, sheet_name: str) -> str:
    return f"{BACKUP_PREFIX}{backup_id}_{sheet_name}"


def _backup_ids(doc) -> list[str]:
    ids = set()
    for ws in doc.worksheets():
        if ws.title.startswith(BACKUP_PREFIX):
            remainder = ws.title[len(BACKUP_PREFIX):]
            backup_id, sep, _ = remainder.rpartition("_")
            if sep and backup_id:
                ids.add(backup_id)
    return sorted(ids, reverse=True)


def _remove_expired_backups(doc) -> None:
    for backup_id in _backup_ids(doc)[BACKUP_LIMIT:]:
        for ws in doc.worksheets():
            if ws.title.startswith(f"{BACKUP_PREFIX}{backup_id}_"):
                try:
                    doc.del_worksheet(ws)
                except Exception:
                    log.exception("만료 백업 삭제 실패: %s", ws.title)


def create_master_backup(doc=None) -> str:
    doc = doc or get_sheet()
    backup_id = _stamp()
    for sheet_name in config.MASTER_SHEET_NAMES:
        source = doc.worksheet(sheet_name)
        doc.duplicate_sheet(source.id, new_sheet_name=_backup_sheet_name(backup_id, sheet_name))
    _remove_expired_backups(doc)
    log.info("마스터 백업 생성: %s", backup_id)
    return backup_id


def get_master_backup_ids() -> list[str]:
    try:
        return _backup_ids(get_sheet())
    except Exception:
        log.exception("백업 목록 조회 실패")
        return []


def restore_master_backup(backup_id: str) -> Result:
    """[패치 ①] 복구도 원자적 교체 방식으로 수행한다."""
    owner = st.session_state.get("_session_id", "unknown")
    doc = None
    try:
        doc = get_sheet()
        lock = acquire_write_lock(doc, owner)
        if not lock:
            return lock

        snapshot = {}
        for sheet_name in config.MASTER_SHEET_NAMES:
            ws = doc.worksheet(_backup_sheet_name(backup_id, sheet_name))
            snapshot[sheet_name] = ws.get_all_values()

        current_backup_id = create_master_backup(doc)

        for sheet_name, values in snapshot.items():
            _atomic_replace_worksheet(doc, sheet_name, values)

        _get_master_items_raw.clear()
        return Result.success(
            f"{backup_id} 백업으로 복구했습니다. 복구 전 데이터는 {current_backup_id} 백업에 보관되었습니다.",
            restored_from=backup_id, safety_backup=current_backup_id,
        )
    except gspread.exceptions.WorksheetNotFound:
        log.exception("백업 시트 없음: %s", backup_id)
        return Result.failure(f"{backup_id} 백업 시트를 찾을 수 없습니다.", code="not_found")
    except Exception as exc:
        return _fail_from_exc(exc, "백업 복구")
    finally:
        if doc is not None:
            release_write_lock(doc, owner)


# ═══════════════════════════════════════════════════════════
# 5. [패치 ②] 마스터 읽기 — 실패를 삼키지 않는다
# ═══════════════════════════════════════════════════════════
@st.cache_data(ttl=600, show_spinner=False)
def _get_master_items_raw(sheet_name: str) -> tuple[pd.DataFrame, str | None]:
    """(DataFrame, 오류메시지) 반환. 오류 시에도 빈 DF를 주지만 사유를 함께 전달한다."""
    try:
        ws = get_sheet().worksheet(sheet_name)
        records = ws.get_all_records()
        if not records:
            return pd.DataFrame(columns=config.MASTER_ALL_COLUMNS), None

        df = pd.DataFrame(records)
        for col in config.MASTER_BASE_COLUMNS:
            if col not in df.columns:
                df[col] = ""

        # 부가 컬럼(category_large 등)을 보존하여 재저장 시 유실을 막는다.
        ordered = [c for c in config.MASTER_ALL_COLUMNS if c in df.columns]
        extras = [c for c in df.columns if c not in ordered and c != "구분"]
        df = df[ordered + extras]
        df["unit_price"] = pd.to_numeric(df["unit_price"], errors="coerce").fillna(0)
        return df, None
    except Exception as exc:
        log.exception("마스터 시트 읽기 실패: %s", sheet_name)
        return (pd.DataFrame(columns=config.MASTER_ALL_COLUMNS),
                f"'{sheet_name}' 시트 읽기 오류: {type(exc).__name__} - {exc}")


def _record_error(message: str | None) -> None:
    if not message:
        return
    bucket = st.session_state.setdefault(ERR_KEY, [])
    if message not in bucket:
        bucket.append(message)


def consume_load_errors() -> list[str]:
    """UI가 한 번 표시하고 비우는 읽기 오류 목록."""
    return st.session_state.pop(ERR_KEY, [])


def get_filtered_master_items(sheet_name: str = "자재비", search_keyword: str = "") -> pd.DataFrame:
    df, err = _get_master_items_raw(sheet_name)
    _record_error(err)
    if search_keyword:
        kw = str(search_keyword).strip()
        mask = df["item_name"].astype(str).str.contains(kw, case=False, na=False)
        if "spec" in df.columns:
            mask = mask | df["spec"].astype(str).str.contains(kw, case=False, na=False)
        df = df[mask]
    return df.reset_index(drop=True)


def get_all_master_items_combined(search_keyword: str = "") -> pd.DataFrame:
    """마스터 4개 시트를 '구분'(시트명) 열과 함께 병합."""
    frames = []
    for sheet_name in config.MASTER_SHEET_NAMES:
        df = get_filtered_master_items(sheet_name, search_keyword).copy()
        df.insert(0, "구분", sheet_name)
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["구분"] + config.MASTER_ALL_COLUMNS)
    return pd.concat(frames, ignore_index=True)


def get_unit_price(item_name: str, sheet_name: str | None = None) -> float:
    try:
        if sheet_name:
            df, err = _get_master_items_raw(sheet_name)
            _record_error(err)
            hit = df[df["item_name"] == item_name]
            return float(hit.iloc[0]["unit_price"]) if not hit.empty else 0.0

        frames = []
        for name in config.MASTER_SHEET_NAMES:
            df, err = _get_master_items_raw(name)
            _record_error(err)
            frames.append(df)
        combined = pd.concat(frames, ignore_index=True) \
                     .drop_duplicates(subset=["item_name"], keep="first")
        price_map = combined.set_index("item_name")["unit_price"].to_dict()
        return float(price_map.get(item_name, 0.0) or 0.0)
    except Exception:
        log.exception("단가 조회 실패: %s", item_name)
        return 0.0


# ═══════════════════════════════════════════════════════════
# 6. 프로젝트 저장소
# ═══════════════════════════════════════════════════════════
@st.cache_data(ttl=120, show_spinner=False)
def get_cloud_projects_list() -> list[dict]:
    try:
        ws = get_sheet().worksheet(config.PROJECT_SHEET)
        records = ws.get_all_records()
        return [{"name": str(r.get("project_name", "이름없음")),
                 "date": str(r.get("date", ""))} for r in records]
    except Exception as exc:
        log.exception("클라우드 프로젝트 목록 조회 실패")
        _record_error(f"클라우드 목록 조회 오류: {exc}")
        return []


def load_project_from_cloud(project_name: str) -> Result:
    """[패치 ③] 성공 시 Result.data = (DataFrame, 저장시각)."""
    try:
        ws = get_sheet().worksheet(config.PROJECT_SHEET)
        for row in ws.get_all_values()[1:]:
            padded = list(row) + ["", "", ""]
            saved_name, saved_date, payload = padded[0:3]
            if saved_name != project_name:
                continue
            if not payload:
                return Result.failure("저장된 데이터가 비어 있습니다.", code="not_found")
            df = pd.DataFrame(json.loads(payload))
            return Result.success(f"'{project_name}' 불러오기 완료",
                                  data=(df, saved_date), version=saved_date)
        return Result.failure("클라우드에서 해당 프로젝트를 찾을 수 없습니다.", code="not_found")
    except json.JSONDecodeError as exc:
        log.exception("프로젝트 JSON 파싱 실패: %s", project_name)
        return Result.failure(f"저장 데이터 형식 오류: {exc}", code="invalid")
    except Exception as exc:
        return _fail_from_exc(exc, "프로젝트 불러오기")


def save_project_to_cloud(project_name: str, df: pd.DataFrame,
                          expected_version: str | None = None) -> Result:
    """프로젝트를 저장한다. 동시 저장은 잠금과 버전 검사로 차단한다."""
    owner = st.session_state.get("_session_id", "unknown")
    doc = None
    try:
        doc = get_sheet()
        lock = acquire_write_lock(doc, owner)
        if not lock:
            return lock

        ws = doc.worksheet(config.PROJECT_SHEET)
        payload = df.copy()
        for col in config.ESTIMATE_DATE_COLUMNS:
            if col in payload.columns:
                payload[col] = pd.to_datetime(payload[col], errors="coerce")                                  .dt.strftime("%Y-%m-%d").fillna("")
        data_json = payload.to_json(orient="records", force_ascii=False)

        records = ws.get_all_records()
        row_idx, stored_date = -1, None
        for i, record in enumerate(records):
            if str(record.get("project_name", "")) == str(project_name):
                row_idx, stored_date = i + 2, str(record.get("date", ""))
                break

        if row_idx != -1 and expected_version is not None and stored_date != expected_version:
            return Result.failure(
                f"다른 사용자가 {stored_date}에 저장했습니다. 최신본을 다시 불러와 확인하세요.",
                code="conflict", data=stored_date,
            )

        now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        values = [[project_name, now_str, data_json]]
        if row_idx != -1:
            ws.update(values, f"A{row_idx}:C{row_idx}", value_input_option="USER_ENTERED")
        else:
            ws.append_row(values[0], value_input_option="USER_ENTERED")

        get_cloud_projects_list.clear()
        log.info("프로젝트 저장: %s (%d행)", project_name, len(df))
        return Result.success("클라우드 저장 완료", data=now_str, version=now_str)
    except Exception as exc:
        return _fail_from_exc(exc, "프로젝트 저장")
    finally:
        if doc is not None:
            release_write_lock(doc, owner)


def delete_project_from_cloud(project_name: str) -> Result:
    """클라우드 저장본을 영구 삭제한다. 저장과 같은 잠금 규칙을 적용한다."""
    owner = st.session_state.get("_session_id", "unknown")
    doc = None
    try:
        doc = get_sheet()
        lock = acquire_write_lock(doc, owner)
        if not lock:
            return lock

        ws = doc.worksheet(config.PROJECT_SHEET)
        names = ws.col_values(1)
        if str(project_name) not in names:
            return Result.failure("클라우드에서 해당 프로젝트를 찾을 수 없습니다.", code="not_found")

        ws.delete_rows(names.index(str(project_name)) + 1)
        get_cloud_projects_list.clear()
        log.info("프로젝트 삭제(클라우드): %s", project_name)
        return Result.success(f"'{project_name}'을 클라우드에서 삭제했습니다.")
    except Exception as exc:
        return _fail_from_exc(exc, "클라우드 프로젝트 삭제")
    finally:
        if doc is not None:
            release_write_lock(doc, owner)


# ═══════════════════════════════════════════════════════════
# 7. [패치 ①④] 마스터 일괄 저장
# ═══════════════════════════════════════════════════════════
def _prepare_master_frame(df: pd.DataFrame) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    """'구분'을 시트명으로 정규화하고 시트별로 분리. 인식 불가 값은 별도 집계."""
    work = df.copy()
    if "구분" not in work.columns:
        raise ValueError("'구분' 컬럼이 없습니다.")

    work["_sheet"] = work["구분"].map(config.normalize_sheet_name)

    unknown = work[work["_sheet"].isna()]
    unknown_counts = (unknown["구분"].astype(str).str.strip()
                      .value_counts().to_dict()) if not unknown.empty else {}

    buckets: dict[str, pd.DataFrame] = {}
    for sheet_name in config.MASTER_SHEET_NAMES:
        part = work[work["_sheet"] == sheet_name].drop(columns=["_sheet", "구분"], errors="ignore")
        ordered = [c for c in config.MASTER_ALL_COLUMNS if c in part.columns]
        extras = [c for c in part.columns if c not in ordered]
        buckets[sheet_name] = part[ordered + extras]
    return buckets, unknown_counts


def upload_combined_dataframe_to_master(df: pd.DataFrame) -> Result:
    """마스터 4개 시트를 원자적으로 갱신한다.

    [패치 ④] 기존에는 df['구분'] == '자재비' 정확 일치만 살아남아, '자재'처럼
             표기가 다른 행이 조용히 사라졌다. 이제 정규화 후 인식 불가 값이 있으면
             저장을 중단하고 어떤 값이 문제인지 알려준다.
    """
    owner = st.session_state.get("_session_id", "unknown")
    doc = None
    try:
        buckets, unknown = _prepare_master_frame(df)
        if unknown:
            detail = ", ".join(f"'{k}'({v}건)" for k, v in list(unknown.items())[:5])
            return Result.failure(
                f"인식할 수 없는 '구분' 값이 있어 저장을 중단했습니다: {detail}. "
                f"허용 값: {', '.join(config.MASTER_SHEET_NAMES)}",
                code="invalid", data=unknown,
            )

        doc = get_sheet()
        lock = acquire_write_lock(doc, owner)
        if not lock:
            return lock

        backup_id = create_master_backup(doc)

        for sheet_name, part in buckets.items():
            values = [list(part.columns)] + part.fillna("").astype(object).values.tolist()
            _atomic_replace_worksheet(doc, sheet_name, values)

        _get_master_items_raw.clear()
        total = sum(len(p) for p in buckets.values())
        return Result.success(
            f"저장 완료! (총 {total:,}건) 저장 전 데이터는 {backup_id} 백업으로 보관되었습니다.",
            backup_id=backup_id, rows=total,
        )
    except ValueError as exc:
        log.warning("마스터 저장 입력값 오류: %s", exc)
        return Result.failure(str(exc), code="invalid")
    except Exception as exc:
        return _fail_from_exc(exc, "마스터 DB 저장")
    finally:
        if doc is not None:
            release_write_lock(doc, owner)
