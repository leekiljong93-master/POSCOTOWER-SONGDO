# -*- coding: utf-8 -*-
"""
selftest_auth.py — 패치 ⑥ 편집 권한 통제 검증
실행: python selftest_auth.py
"""

import datetime as _dt
import sys

import auth

# ── Windows 한글 콘솔(cp949) 출력 호환 ────────────────────────
# cp949 에는 ═ ✅ ❌ 💥 ⬜ ⚠️ 문자가 없어 그대로 출력하면
# UnicodeEncodeError 로 프로그램이 중단된다. 아래에서 두 겹으로 막는다.
#   ① 스트림 errors="replace"  → 어떤 문자가 와도 중단되지 않음
#   ② 인코딩이 좁으면 ASCII 기호로 자동 대체 → 화면이 깨지지 않음
def _init_console():
    for _name in ("stdout", "stderr"):
        _stream = getattr(sys, _name, None)
        try:
            _stream.reconfigure(errors="replace")
        except Exception:
            pass
    import os
    _plain = {"bar": "=", "ok": "[OK]", "no": "[FAIL]", "boom": "[ERROR]",
              "none": "[NONE]", "warn": "[!]"}
    if os.getenv("PTS_ASCII") == "1":      # 실행기가 좁은 콘솔이라고 알려준 경우
        return _plain
    _enc = (getattr(sys.stdout, "encoding", "") or "ascii")
    try:
        "═✅❌💥⬜".encode(_enc)
        return {"bar": "═", "ok": "✅", "no": "❌", "boom": "💥",
                "none": "⬜", "warn": "⚠️"}
    except Exception:
        return _plain


SYM = _init_console()
BAR = SYM["bar"]

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"  → {detail}" if detail and not cond else ""))


now = _dt.datetime(2026, 7, 30, 17, 0, 0)

print("=== 비밀번호 해시/검증 ===")
h = auth.hash_password("PTS!songdo2026")
check("해시 길이 64자(SHA-256)", len(h) == 64, h)
check("동일 입력 → 동일 해시", h == auth.hash_password("PTS!songdo2026"))
check("정답 통과", auth.verify_password("PTS!songdo2026", h) is True)
check("오답 거부", auth.verify_password("wrongpass", h) is False)
check("대소문자 구분", auth.verify_password("pts!songdo2026", h) is False)
check("빈 비밀번호 거부", auth.verify_password("", h) is False)
check("해시 미설정 시 거부", auth.verify_password("anything", None) is False)
check("해시 대문자 표기 허용", auth.verify_password("PTS!songdo2026", h.upper()) is True)
check("평문이 해시에 노출되지 않음", "songdo" not in h)

print("\n=== 세션 TTL 자동 잠금 ===")
check("미인증 상태는 만료", auth.is_session_expired(None, now) is True)
check("인증 직후 유효", auth.is_session_expired(now - _dt.timedelta(minutes=1), now) is False)
check("89분 경과 유효", auth.is_session_expired(now - _dt.timedelta(minutes=89), now) is False)
check("91분 경과 만료", auth.is_session_expired(now - _dt.timedelta(minutes=91), now) is True)

print("\n=== 무단 대입 잠금 ===")
check("실패 0회는 시도 가능", auth.lockout_seconds_left(0, None, now) == 0)
check("실패 4회는 시도 가능", auth.lockout_seconds_left(4, now, now) == 0)
locked = auth.lockout_seconds_left(5, now, now)
check("실패 5회 → 잠금(600초)", locked == 600, locked)
check("잠금 5분 후 잔여 300초",
      auth.lockout_seconds_left(5, now - _dt.timedelta(minutes=5), now) == 300)
check("잠금 10분 경과 후 해제",
      auth.lockout_seconds_left(5, now - _dt.timedelta(minutes=11), now) == 0)

print("\n=== 설정 상수 ===")
check("TTL 90분", auth.SESSION_TTL_MIN == 90)
check("최대 실패 5회", auth.MAX_FAILURES == 5)
check("감사로그 시트명", auth.AUDIT_SHEET == "_감사로그")
check("감사 항목 5열", len(auth.AUDIT_HEADER) == 5, auth.AUDIT_HEADER)

print("\n" + BAR * 55)
print(f"결과: {len(PASS)}건 통과 / {len(FAIL)}건 실패")
# 기계판독용 (ASCII 전용 → 어떤 콘솔 인코딩에서도 깨지지 않음)
print(f"PTS_RESULT PASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    print("실패: " + ", ".join(FAIL))
    sys.exit(1)
print("모든 검증을 통과했습니다.")
