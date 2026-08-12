# -*- coding: utf-8 -*-
"""
auth.py
─────────────────────────────────────────────────────────────
[패치 ⑥] 편집 권한 통제

문제
  Streamlit 앱 URL을 아는 사람은 누구나 마스터 단가를 수정하고,
  백업을 덮어쓰고, 클라우드 프로젝트를 삭제할 수 있었다.
  (Google Sheets 서비스 계정 권한을 앱이 그대로 대행하므로 사실상 편집자 권한)

설계 방침
  · 조회(읽기)는 그대로 개방한다 → 실무자 확인·보고 목적을 막지 않는다.
  · 변경(쓰기)만 잠근다 → 마스터 저장 / 백업 복구 / 클라우드 저장·삭제 / 대량 업로드
  · 비밀번호는 평문이 아닌 SHA-256 해시로 secrets에 보관한다.
  · 무단 대입(brute force) 방지를 위해 실패 횟수 기반 지연 잠금을 둔다.
  · 누가 언제 무엇을 바꿨는지 감사 로그를 남긴다. (중대재해·감사 대응 시 필요)

CLI 사용법 — 비밀번호 해시 생성
    python auth.py "원하는비밀번호"
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import hmac
import sys

import streamlit as st

import config

log = config.get_logger("auth")

# ═══════════════════════════════════════════════════════════
# 0. 설정값
# ═══════════════════════════════════════════════════════════
SESSION_TTL_MIN = 90          # 인증 유효 시간(분). 경과 시 자동 잠금
MAX_FAILURES = 5              # 연속 실패 허용 횟수
LOCKOUT_MIN = 10              # 초과 시 잠금 시간(분)
AUDIT_SHEET = "_감사로그"
AUDIT_HEADER = ["시각", "작성자", "세션ID", "작업", "상세"]

_K_UNLOCKED = "_auth_unlocked_at"
_K_FAILS = "_auth_fail_count"
_K_LAST_FAIL = "_auth_last_fail_at"
_K_EDITOR = "_auth_editor_name"


# ═══════════════════════════════════════════════════════════
# 1. 순수 로직 (streamlit 없이 단위 검증 가능)
# ═══════════════════════════════════════════════════════════
def hash_password(password: str) -> str:
    """비밀번호를 SHA-256 16진 문자열로 변환."""
    return hashlib.sha256(str(password).encode("utf-8")).hexdigest()


def verify_password(password: str, expected_hash: str) -> bool:
    """타이밍 공격에 안전한 비교."""
    if not password or not expected_hash:
        return False
    return hmac.compare_digest(hash_password(password), str(expected_hash).strip().lower())


def is_session_expired(unlocked_at, now=None, ttl_min: int = SESSION_TTL_MIN) -> bool:
    """인증 후 TTL이 지났는지 판정."""
    if not unlocked_at:
        return True
    now = now or _dt.datetime.now()
    return (now - unlocked_at).total_seconds() > ttl_min * 60


def lockout_seconds_left(fail_count: int, last_fail_at, now=None,
                         max_fail: int = MAX_FAILURES,
                         lockout_min: int = LOCKOUT_MIN) -> int:
    """무단 대입 잠금 잔여 초. 0이면 시도 가능."""
    if fail_count < max_fail or not last_fail_at:
        return 0
    now = now or _dt.datetime.now()
    elapsed = (now - last_fail_at).total_seconds()
    remaining = lockout_min * 60 - elapsed
    return int(remaining) if remaining > 0 else 0


# ═══════════════════════════════════════════════════════════
# 2. 설정 조회
# ═══════════════════════════════════════════════════════════
def _expected_hash() -> str | None:
    """secrets에서 기대 해시를 얻는다.

    권장: EDIT_PASSWORD_SHA256 (해시 보관)
    허용: EDIT_PASSWORD (평문 → 즉시 해시. 마이그레이션 편의용)
    """
    try:
        value = st.secrets.get("EDIT_PASSWORD_SHA256")
        if value:
            return str(value).strip().lower()
        plain = st.secrets.get("EDIT_PASSWORD")
        if plain:
            log.warning("EDIT_PASSWORD(평문)가 사용되었습니다. EDIT_PASSWORD_SHA256 로 교체를 권장합니다.")
            return hash_password(plain)
    except Exception:
        log.exception("secrets 조회 실패")
    return None


def is_configured() -> bool:
    return _expected_hash() is not None


# ═══════════════════════════════════════════════════════════
# 3. 권한 판정
# ═══════════════════════════════════════════════════════════
def can_edit() -> bool:
    """현재 세션이 편집 권한을 가졌는지 반환.

    비밀번호가 설정되지 않은 환경에서는 기존 동작(전원 편집 가능)을 유지한다.
    단, 화면에 경고를 표시해 방치되지 않도록 한다.
    """
    if not is_configured():
        return True

    unlocked_at = st.session_state.get(_K_UNLOCKED)
    if is_session_expired(unlocked_at):
        if unlocked_at:
            st.session_state[_K_UNLOCKED] = None
            log.info("편집 권한 만료 (TTL %d분)", SESSION_TTL_MIN)
        return False
    return True


def editor_name() -> str:
    """감사 로그에 기록할 편집자 표기."""
    return (st.session_state.get(_K_EDITOR)
            or st.session_state.get("writer_name")
            or "미지정")


def require_edit(action: str = "이 작업") -> bool:
    """쓰기 작업 직전 호출. 권한 없으면 안내 후 False."""
    if can_edit():
        return True
    st.warning(f"🔒 {action}은 편집 권한이 필요합니다. 사이드바 **편집 권한**에서 잠금을 해제하세요.")
    return False


# ═══════════════════════════════════════════════════════════
# 4. 로그인 / 로그아웃
# ═══════════════════════════════════════════════════════════
def _unlock(name: str) -> None:
    st.session_state[_K_UNLOCKED] = _dt.datetime.now()
    st.session_state[_K_FAILS] = 0
    st.session_state[_K_EDITOR] = (name or "").strip() or "미지정"
    log.info("편집 권한 해제: %s", st.session_state[_K_EDITOR])


def lock() -> None:
    st.session_state[_K_UNLOCKED] = None
    log.info("편집 권한 잠금")


def render_sidebar_login() -> None:
    """사이드바 편집 권한 위젯. app.py에서 1회 호출한다."""
    st.sidebar.divider()
    st.sidebar.subheader("🔐 편집 권한")

    if not is_configured():
        st.sidebar.warning(
            "편집 비밀번호가 설정되지 않아 **누구나 데이터를 변경**할 수 있습니다.\n\n"
            "`secrets.toml`에 `EDIT_PASSWORD_SHA256` 을 추가하세요."
        )
        return

    if can_edit():
        unlocked_at = st.session_state.get(_K_UNLOCKED)
        left = SESSION_TTL_MIN - int((_dt.datetime.now() - unlocked_at).total_seconds() // 60)
        st.sidebar.success(f"✅ 편집 가능 — {editor_name()}\n\n자동 잠금까지 약 {max(left, 0)}분")
        if st.sidebar.button("🔒 지금 잠그기", use_container_width=True):
            lock()
            st.rerun()
        return

    # 잠금 상태
    wait = lockout_seconds_left(st.session_state.get(_K_FAILS, 0),
                               st.session_state.get(_K_LAST_FAIL))
    if wait > 0:
        st.sidebar.error(f"⛔ 시도 횟수 초과. {wait // 60}분 {wait % 60}초 후 다시 시도하세요.")
        return

    st.sidebar.caption("조회는 자유롭게 가능하며, 데이터 변경 시에만 인증이 필요합니다.")
    with st.sidebar.form("auth_form", clear_on_submit=True):
        name = st.text_input("편집자 이름", value=st.session_state.get(_K_EDITOR, ""),
                             placeholder="예: 이길종 주무")
        pw = st.text_input("편집 비밀번호", type="password")
        submitted = st.form_submit_button("🔓 잠금 해제", use_container_width=True,
                                          type="primary")

    if not submitted:
        return

    if verify_password(pw, _expected_hash()):
        _unlock(name)
        st.rerun()
    else:
        fails = st.session_state.get(_K_FAILS, 0) + 1
        st.session_state[_K_FAILS] = fails
        st.session_state[_K_LAST_FAIL] = _dt.datetime.now()
        left = MAX_FAILURES - fails
        log.warning("편집 권한 인증 실패 (%d회)", fails)
        if left > 0:
            st.sidebar.error(f"비밀번호가 올바르지 않습니다. (남은 시도 {left}회)")
        else:
            st.sidebar.error(f"시도 횟수를 초과했습니다. {LOCKOUT_MIN}분간 잠깁니다.")


# ═══════════════════════════════════════════════════════════
# 5. 감사 로그
# ═══════════════════════════════════════════════════════════
def audit(action: str, detail: str = "") -> None:
    """변경 이력을 스프레드시트에 기록한다. 실패해도 본 작업을 막지 않는다."""
    try:
        import db_manager as db

        doc = db.get_sheet()
        try:
            ws = doc.worksheet(AUDIT_SHEET)
        except Exception:
            ws = doc.add_worksheet(title=AUDIT_SHEET, rows="2000", cols="6")
            ws.append_row(AUDIT_HEADER)

        ws.append_row([
            _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            editor_name(),
            st.session_state.get("_session_id", ""),
            action,
            str(detail)[:500],
        ], value_input_option="USER_ENTERED")
        log.info("감사 로그 기록: %s | %s", action, detail)
    except Exception:
        log.exception("감사 로그 기록 실패 (본 작업은 계속 진행)")


# ═══════════════════════════════════════════════════════════
# 6. CLI — 비밀번호 해시 생성
# ═══════════════════════════════════════════════════════════
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("사용법: python auth.py \"원하는비밀번호\"")
        sys.exit(1)
    print("\n.streamlit/secrets.toml 에 아래 줄을 추가하세요:\n")
    print(f'EDIT_PASSWORD_SHA256 = "{hash_password(sys.argv[1])}"\n')
