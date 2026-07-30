# -*- coding: utf-8 -*-
"""
state_manager.py
─────────────────────────────────────────────────────────────
[패치 ⑤] 이중 상태 관리 제거

기존 구조는 st.session_state.projects[name] 과 st.session_state.estimate_data 가
서로를 복사(copy)하며 동거하는 형태였다. 두 곳 중 한쪽만 갱신되는 순간
"화면과 저장본 불일치"가 발생한다.

이 모듈에서는 다음 원칙을 강제한다.
  · 단일 진실 소스(SSOT) = st.session_state.projects[current_project]
  · estimate_data 는 더 이상 쓰지 않는다. (읽기: get_estimate / 쓰기: set_estimate)
  · 컬럼 정규화·숫자 변환·합계 재계산은 set_estimate 한 곳에서만 수행한다.
"""

from __future__ import annotations

import uuid

import pandas as pd
import streamlit as st

import config

log = config.get_logger("state")

DEFAULT_PROJECT = "기본 프로젝트"

_K_PROJECTS = "projects"
_K_CURRENT = "current_project"
_K_VERSIONS = "project_versions"     # 클라우드 낙관적 동시성 검사용 {프로젝트명: 저장시각}
_K_SESSION_ID = "_session_id"


# ═══════════════════════════════════════════════════════════
# 0. 세션 접근 추상화 (단위 테스트에서 교체 가능하도록 분리)
# ═══════════════════════════════════════════════════════════
def _ss():
    return st.session_state


def session_id() -> str:
    """이 브라우저 세션의 고유 식별자 (쓰기 잠금 소유자 표시에 사용)."""
    ss = _ss()
    if not ss.get(_K_SESSION_ID):
        ss[_K_SESSION_ID] = uuid.uuid4().hex[:12]
    return ss[_K_SESSION_ID]


# ═══════════════════════════════════════════════════════════
# 1. 스키마 정규화
# ═══════════════════════════════════════════════════════════
def empty_estimate() -> pd.DataFrame:
    """빈 내역서. 정규화를 거쳐 dtype까지 표준화한다.

    (정규화하지 않은 빈 프레임을 저장하면 전 컬럼이 object dtype이 되어,
     이후 정규화된 프레임과 비교할 때 매번 '변경됨'으로 오판된다.)
    """
    return normalize_estimate(pd.DataFrame(columns=config.ESTIMATE_COLUMNS))


def normalize_estimate(df: pd.DataFrame | None, *, recompute_total: bool = True) -> pd.DataFrame:
    """내역서 DataFrame을 표준 스키마로 정렬한다.

    · 찌꺼기 컬럼 제거 ('선택' 등)
    · 누락 컬럼 생성, 표준 순서로 재배치 (사용자 추가 컬럼은 뒤에 보존)
    · 숫자/날짜 형 변환
    · '구분' 표기 정규화 (패치 ④ 연계)
    · 합계 = 단가 × 수량 재계산
    """
    if df is None:
        return empty_estimate()

    out = df.copy()

    # 인덱스가 데이터로 승격되는 사고 방지
    out = out.reset_index(drop=True)

    for junk in config.ESTIMATE_JUNK_COLUMNS:
        if junk in out.columns:
            out = out.drop(columns=[junk])

    for col in config.ESTIMATE_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col not in config.ESTIMATE_NUMERIC_COLUMNS else 0

    # 구분 정규화 (인식 불가 값은 원본 보존 → audit 단계에서 사용자에게 경고)
    if "구분" in out.columns and not out.empty:
        normalized = out["구분"].map(config.normalize_gubun)
        out["구분"] = normalized.fillna(out["구분"])

    # 콤마 표기('10,000') 금액이 0원으로 소멸하지 않도록 공용 변환기 사용
    for col in config.ESTIMATE_NUMERIC_COLUMNS:
        out[col] = config.to_number_series(out[col])

    for col in config.ESTIMATE_DATE_COLUMNS:
        out[col] = pd.to_datetime(out[col], errors="coerce")

    if recompute_total and not out.empty:
        out["합계"] = (out["단가"] * out["수량"]).round(0).astype("int64")

    ordered = [c for c in config.ESTIMATE_COLUMNS if c in out.columns]
    extras = [c for c in out.columns if c not in ordered]
    return out[ordered + extras]


# ═══════════════════════════════════════════════════════════
# 2. 초기화
# ═══════════════════════════════════════════════════════════
def bootstrap() -> None:
    """앱 구동 시 1회 호출. 상태가 없거나 깨져 있으면 복구한다."""
    ss = _ss()

    if not isinstance(ss.get(_K_PROJECTS), dict) or not ss.get(_K_PROJECTS):
        ss[_K_PROJECTS] = {DEFAULT_PROJECT: empty_estimate()}
        log.info("세션 상태 초기화: 기본 프로젝트 생성")

    if ss.get(_K_CURRENT) not in ss[_K_PROJECTS]:
        ss[_K_CURRENT] = next(iter(ss[_K_PROJECTS]))

    if not isinstance(ss.get(_K_VERSIONS), dict):
        ss[_K_VERSIONS] = {}

    if "cloud_project_list" not in ss:
        ss["cloud_project_list"] = []

    # 구버전 잔재 정리: estimate_data 가 남아 있으면 SSOT로 흡수한 뒤 삭제
    if "estimate_data" in ss:
        legacy = ss["estimate_data"]
        if isinstance(legacy, pd.DataFrame) and not legacy.empty:
            current = ss[_K_PROJECTS].get(ss[_K_CURRENT])
            if current is None or current.empty:
                ss[_K_PROJECTS][ss[_K_CURRENT]] = normalize_estimate(legacy)
                log.warning("구버전 estimate_data 를 SSOT로 이관했습니다.")
        del ss["estimate_data"]

    # 보관 중인 모든 프로젝트를 표준 스키마로 정렬
    for name, frame in list(ss[_K_PROJECTS].items()):
        ss[_K_PROJECTS][name] = normalize_estimate(frame)


# ═══════════════════════════════════════════════════════════
# 3. 조회
# ═══════════════════════════════════════════════════════════
def project_names() -> list[str]:
    return list(_ss()[_K_PROJECTS].keys())


def current_project() -> str:
    return _ss()[_K_CURRENT]


def get_estimate() -> pd.DataFrame:
    """현재 프로젝트 내역서 사본을 반환 (호출자가 수정해도 SSOT는 안전)."""
    return _ss()[_K_PROJECTS][current_project()].copy()


def is_empty() -> bool:
    return _ss()[_K_PROJECTS][current_project()].empty


def get_version(name: str | None = None) -> str | None:
    """마지막으로 불러오거나 저장한 클라우드 타임스탬프."""
    return _ss()[_K_VERSIONS].get(name or current_project())


def set_version(name: str, stamp: str | None) -> None:
    _ss()[_K_VERSIONS][name] = stamp


# ═══════════════════════════════════════════════════════════
# 4. 변경
# ═══════════════════════════════════════════════════════════
def set_estimate(df: pd.DataFrame, *, recompute_total: bool = True) -> pd.DataFrame:
    """현재 프로젝트 내역서를 갱신한다. (SSOT 단일 기록 지점)"""
    normalized = normalize_estimate(df, recompute_total=recompute_total)
    _ss()[_K_PROJECTS][current_project()] = normalized
    return normalized


def _comparable(df: pd.DataFrame) -> pd.DataFrame:
    """dtype 차이(int64 vs float64)로 오판하지 않도록 값 기준으로 정렬한 사본."""
    out = df.copy().reset_index(drop=True)
    for col in config.ESTIMATE_NUMERIC_COLUMNS:
        if col in out.columns:
            out[col] = config.to_number_series(out[col]).astype("float64")
    for col in config.ESTIMATE_DATE_COLUMNS:
        if col in out.columns:
            out[col] = pd.to_datetime(out[col], errors="coerce")
    for col in out.columns:
        if col not in config.ESTIMATE_NUMERIC_COLUMNS + config.ESTIMATE_DATE_COLUMNS:
            out[col] = out[col].fillna("").astype(str)
    return out


def has_changed(candidate: pd.DataFrame) -> bool:
    """data_editor 반환값이 실제로 SSOT와 다른지 판정 (불필요한 rerun 방지)."""
    current = _ss()[_K_PROJECTS][current_project()]
    incoming = normalize_estimate(candidate)
    if current.shape != incoming.shape or list(current.columns) != list(incoming.columns):
        return True
    return not _comparable(current).equals(_comparable(incoming))


def create_project(name: str) -> tuple[bool, str]:
    name = (name or "").strip()
    if not name:
        return False, "프로젝트명을 입력하세요."
    ss = _ss()
    if name in ss[_K_PROJECTS]:
        return False, "이미 존재하는 프로젝트입니다."
    ss[_K_PROJECTS][name] = empty_estimate()
    ss[_K_CURRENT] = name
    log.info("프로젝트 생성: %s", name)
    return True, f"'{name}' 프로젝트를 생성했습니다."


def switch_project(name: str) -> None:
    ss = _ss()
    if name in ss[_K_PROJECTS]:
        ss[_K_CURRENT] = name


def replace_project(name: str, df: pd.DataFrame, *, version: str | None = None) -> None:
    """클라우드에서 불러온 데이터로 프로젝트를 교체하고 현재 프로젝트로 전환."""
    ss = _ss()
    ss[_K_PROJECTS][name] = normalize_estimate(df)
    ss[_K_CURRENT] = name
    set_version(name, version)
    log.info("프로젝트 로드: %s (version=%s)", name, version)


def delete_project(name: str) -> tuple[bool, str]:
    """세션 목록에서만 제거한다. (클라우드 저장본은 유지)"""
    ss = _ss()
    if name not in ss[_K_PROJECTS]:
        return False, "존재하지 않는 프로젝트입니다."
    if len(ss[_K_PROJECTS]) <= 1:
        # 마지막 프로젝트는 삭제 대신 초기화
        ss[_K_PROJECTS][name] = empty_estimate()
        return True, f"'{name}'의 내역을 모두 비웠습니다."

    del ss[_K_PROJECTS][name]
    ss[_K_VERSIONS].pop(name, None)
    if ss[_K_CURRENT] == name:
        ss[_K_CURRENT] = next(iter(ss[_K_PROJECTS]))
    log.info("프로젝트 삭제(세션): %s", name)
    return True, f"'{name}'을 현재 목록에서 삭제했습니다."


def clear_current() -> None:
    """현재 프로젝트 내역만 비운다 (컬럼 구조 유지)."""
    _ss()[_K_PROJECTS][current_project()] = empty_estimate()
    log.info("내역 전체 삭제: %s", current_project())
