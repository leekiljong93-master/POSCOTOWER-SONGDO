# -*- coding: utf-8 -*-
"""
test_1_core.py - 기반 패치 ①~⑤ 검증
─────────────────────────────────────────────────────────────
대상: config.py · state_manager.py · db_manager.py · logic_calculator.py

실행: python test_1_core.py
"""

import sys

import pandas as pd

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
    """detail 에 numpy 배열/Series 가 와도 진리값 판정이 모호해지지 않도록 문자열화."""
    ok = bool(cond)
    (PASS if ok else FAIL).append(name)
    suffix = ""
    if not ok:
        text = str(detail).strip()
        if text:
            suffix = f"  → {text}"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")


class FakeSessionState(dict):
    """streamlit 세션 상태 대역 (서버 없이 state_manager 검증)."""

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError as exc:
            raise AttributeError(key) from exc

    def __setattr__(self, key, value):
        self[key] = value


# ═══════════════════════════════════════════════════════════
# ④ 구분 체계 일원화
# ═══════════════════════════════════════════════════════════
import config
import logic_calculator as calc

print("=== ④ 구분 체계 일원화 ===")
check("'자재비' → '자재'", config.normalize_gubun("자재비") == "자재")
check("' 인건비 ' → '노무'", config.normalize_gubun(" 인건비 ") == "노무")
check("'기계경비' → '장비'", config.normalize_gubun("기계경비") == "장비")
check("'자재' → 시트명 '자재비'", config.normalize_sheet_name("자재") == "자재비")
check("'세트' 원가 비목 = 자재", config.cost_group_of("세트") == "자재")
check("미지의 값은 None", config.normalize_gubun("ETC") is None)

# 표기가 뒤섞인 내역서 - 구버전이라면 자재/장비/세트 금액이 누락된다
df_mixed = pd.DataFrame([
    {"구분": "자재", "공종명": "A", "합계": 1_000_000},
    {"구분": "자재비", "공종명": "B", "합계": 2_000_000},   # 구버전 누락
    {"구분": "노무", "공종명": "C", "합계": 3_000_000},
    {"구분": "인건비", "공종명": "D", "합계": 1_500_000},   # 구버전 누락
    {"구분": "세트", "공종명": "E", "합계": 500_000},       # 구버전 누락
    {"구분": "장비", "공종명": "F", "합계": "800,000"},     # 콤마 문자열
])
audit = calc.audit_categories(df_mixed)
check("자재 집계 = 3,500,000", audit["counted"]["자재"] == 3_500_000, audit["counted"])
check("노무 집계 = 4,500,000", audit["counted"]["노무"] == 4_500_000, audit["counted"])
check("장비 집계 = 800,000 (콤마 파싱)", audit["counted"]["장비"] == 800_000,
      audit["counted"])
check("미인식 행 없음", audit["unknown_rows"] == 0, audit["unknown"])

summary = calc.calculate_cost_summary(df_mixed, config.DEFAULT_RATES)
material = next(r for r in summary if r["비목"] == "1. 재료비")
check("갑지 재료비 = 3,500,000", material["금액(원)"] == "3,500,000", material)

df_bad = pd.DataFrame([{"구분": "기타", "공종명": "X", "합계": 999_000}])
audit_bad = calc.audit_categories(df_bad)
check("미인식 값 탐지",
      audit_bad["unknown_rows"] == 1 and audit_bad["unknown"]["기타"] == 999_000,
      audit_bad)

check("빈 내역서 처리",
      calc.calculate_cost_summary(pd.DataFrame(), config.DEFAULT_RATES)[0]["금액(원)"] == "0")

df_small = pd.DataFrame([{"구분": "자재", "공종명": "S", "합계": 1_000_000}])
safety = next(r for r in calc.calculate_cost_summary(df_small, config.DEFAULT_RATES)
              if "산업안전보건관리비" in r["비목"])
check("2천만원 미만 안전관리비 제외", safety["금액(원)"] == "0", safety)

print("\n=== 콤마 금액 파싱 (금액 소실 방지) ===")
check("'10,000' → 10000",
      float(config.to_number_series(["10,000"]).iloc[0]) == 10000.0)
check("'₩1,200,000 원' → 1200000",
      float(config.to_number_series(["₩1,200,000 원"]).iloc[0]) == 1200000.0)
check("숫자형은 그대로",
      float(config.to_number_series([5000]).iloc[0]) == 5000.0)
check("해석 불가 값은 0",
      float(config.to_number_series(["없음"]).iloc[0]) == 0.0)

# ═══════════════════════════════════════════════════════════
# ⑤ 단일 상태 관리 (SSOT)
# ═══════════════════════════════════════════════════════════
print("\n=== ⑤ 단일 상태 관리 ===")
import state_manager as state

fake = FakeSessionState()
state._ss = lambda: fake          # 세션 접근만 교체

state.bootstrap()
check("기본 프로젝트 생성", state.project_names() == ["기본 프로젝트"])
check("estimate_data 키 미존재", "estimate_data" not in fake)

state.set_estimate(pd.DataFrame([
    {"구분": "자재비", "공종명": "철근", "단가": "10,000", "수량": 3, "선택": True},
]))
df = state.get_estimate()
check("찌꺼기 '선택' 컬럼 제거", "선택" not in df.columns)
check("구분 정규화 적용", df.loc[0, "구분"] == "자재")
check("합계 자동 재계산", int(df.loc[0, "합계"]) == 30_000, df.to_dict("records"))
check("컬럼 표준 순서",
      list(df.columns)[:4] == ["구분", "공종명", "규격", "단위"], list(df.columns))

mutated = state.get_estimate()
mutated.loc[0, "합계"] = 99
check("사본 수정이 SSOT를 오염시키지 않음",
      int(state.get_estimate().loc[0, "합계"]) == 30_000)

ok, _ = state.create_project("2차 현장")
check("프로젝트 생성/전환", ok and state.current_project() == "2차 현장")
check("이전 프로젝트 데이터 보존",
      int(fake["projects"]["기본 프로젝트"].loc[0, "합계"]) == 30_000)

ok, _ = state.create_project("2차 현장")
check("중복 프로젝트명 거부", not ok)

check("변경 없음 판정", state.has_changed(state.get_estimate()) is False)
check("변경 있음 판정", state.has_changed(pd.DataFrame([
    {"구분": "노무", "공종명": "배관공", "단가": 200_000, "수량": 2}])) is True)

state.switch_project("기본 프로젝트")
state.clear_current()
check("전체 비우기",
      state.is_empty() and list(state.get_estimate().columns) == config.ESTIMATE_COLUMNS)

ok, _ = state.delete_project("2차 현장")
check("프로젝트 삭제", ok and "2차 현장" not in state.project_names())

legacy = FakeSessionState()
legacy["estimate_data"] = pd.DataFrame([
    {"구분": "장비비", "공종명": "굴착기", "단가": 500, "수량": 2}])
state._ss = lambda: legacy
state.bootstrap()
check("구버전 estimate_data 이관",
      "estimate_data" not in legacy and int(state.get_estimate().loc[0, "합계"]) == 1_000)

# ═══════════════════════════════════════════════════════════
# ③ 반환 타입 통일 (Result)
# ═══════════════════════════════════════════════════════════
print("\n=== ③ 반환 타입 통일 ===")
try:
    from db_manager import Result
except Exception as exc:
    Result = None
    print(f"[SKIP] db_manager 로드 불가 - {type(exc).__name__}")

if Result is None:
    print("       (gspread/streamlit 환경에서 다시 실행하면 검증됩니다)")
else:
    ok_res = Result.success("저장 완료", data="2026-07-30 10:00:00")
    bad_res = Result.failure("권한 없음", code="error")
    check("성공 Result는 truthy", bool(ok_res) is True)
    check("실패 Result는 falsy", bool(bad_res) is False)
    check("구버전 res['status'] 호환",
          ok_res["status"] == "success" and bad_res["status"] == "error")
    check("구버전 res['message'] 호환", bad_res["message"] == "권한 없음")
    check("code 분기 가능", Result.failure("충돌", code="conflict").code == "conflict")

print("\n" + BAR * 58)
print(f"결과: {len(PASS)}건 통과 / {len(FAIL)}건 실패")
# 기계판독용 (ASCII 전용 → 어떤 콘솔 인코딩에서도 깨지지 않음)
print(f"PTS_RESULT PASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    print("실패: " + ", ".join(FAIL))
    sys.exit(1)
print("모든 검증을 통과했습니다.")
