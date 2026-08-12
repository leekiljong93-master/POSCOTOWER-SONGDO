# -*- coding: utf-8 -*-
"""
selftest_boq.py — 일위대가(세트) 전개 엔진 검증
실행: python selftest_boq.py
"""

import sys

import pandas as pd

import config
import logic_boq as boq

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


# ═══════════════════════════════════════════════════════════
# 준비: 마스터 단가 + 세트구성
# ═══════════════════════════════════════════════════════════
MASTER = pd.DataFrame([
    {"구분": "자재비", "item_name": "백강관", "spec": "50A", "unit": "m", "unit_price": "12,000"},
    {"구분": "자재비", "item_name": "엘보", "spec": "50A", "unit": "EA", "unit_price": 3000},
    {"구분": "자재비", "item_name": "행거", "spec": "", "unit": "EA", "unit_price": 1500},
    {"구분": "인건비", "item_name": "배관공", "spec": "", "unit": "인", "unit_price": 250000},
    {"구분": "인건비", "item_name": "보통인부", "spec": "", "unit": "인", "unit_price": 150000},
    {"구분": "장비비", "item_name": "용접기", "spec": "", "unit": "시간", "unit_price": 20000},
    {"구분": "자재비", "item_name": "미등록자재", "spec": "A", "unit": "EA", "unit_price": 0},
])

SETS = pd.DataFrame([
    # 소화배관 설치(50A): 자재 12,600 + 노무 37,500 + 장비 4,000 = 54,100
    {"set_name": "소화배관 설치(50A)", "seq": 1, "구분": "자재", "item_name": "백강관",
     "spec": "50A", "unit": "m", "소요량": 1.0, "할증률": 5.0},
    {"set_name": "소화배관 설치(50A)", "seq": 2, "구분": "자재", "item_name": "행거",
     "spec": "", "unit": "EA", "소요량": 0.4, "할증률": 0},
    {"set_name": "소화배관 설치(50A)", "seq": 3, "구분": "노무", "item_name": "배관공",
     "spec": "", "unit": "인", "소요량": 0.12, "할증률": 0},
    {"set_name": "소화배관 설치(50A)", "seq": 4, "구분": "노무", "item_name": "보통인부",
     "spec": "", "unit": "인", "소요량": 0.05, "할증률": 0},
    {"set_name": "소화배관 설치(50A)", "seq": 5, "구분": "장비", "item_name": "용접기",
     "spec": "", "unit": "시간", "소요량": 0.2, "할증률": 0},
    # 중첩: 배관 + 부속 (하위 세트 2m 포함)
    {"set_name": "배관 조립일체", "seq": 1, "구분": "세트", "item_name": "소화배관 설치(50A)",
     "spec": "", "unit": "m", "소요량": 2.0, "할증률": 0},
    {"set_name": "배관 조립일체", "seq": 2, "구분": "자재", "item_name": "엘보",
     "spec": "50A", "unit": "EA", "소요량": 1.0, "할증률": 0},
    # 순환 참조 A→B→A
    {"set_name": "순환A", "seq": 1, "구분": "세트", "item_name": "순환B",
     "spec": "", "unit": "식", "소요량": 1, "할증률": 0},
    {"set_name": "순환B", "seq": 1, "구분": "세트", "item_name": "순환A",
     "spec": "", "unit": "식", "소요량": 1, "할증률": 0},
    # 오류 케이스
    {"set_name": "누락포함", "seq": 1, "구분": "자재", "item_name": "존재하지않는자재",
     "spec": "X", "unit": "EA", "소요량": 1, "할증률": 0},
    {"set_name": "단가0", "seq": 1, "구분": "자재", "item_name": "미등록자재",
     "spec": "A", "unit": "EA", "소요량": 1, "할증률": 0},
])

price_index = boq.build_price_index(MASTER)
set_index = boq.build_set_index(SETS)
resolutions = boq.resolve_all_sets(set_index, price_index)

# ═══════════════════════════════════════════════════════════
print("=== 입력 정규화 ===")
check("세트 6종 색인", len(set_index) == 6, list(set_index.keys()))
check("콤마 단가 파싱(백강관 12,000)",
      price_index["exact"][("자재", "백강관", "50A")]["unit_price"] == 12000)
check("시트명→표준구분 정규화(인건비→노무)", ("노무", "배관공", "") in price_index["exact"])
check("빈 시트 처리", boq.build_set_index(None) == {})

print("\n=== 세트 단가 산출 ===")
r = resolutions["소화배관 설치(50A)"]
# 백강관 12,000×1.05=12,600 / 행거 1,500×0.4=600 / 배관공 250,000×0.12=30,000
# 보통인부 150,000×0.05=7,500 / 용접기 20,000×0.2=4,000  → 54,700
check("단가 합계 54,700원", r.unit_price == 54700, r.unit_price)
check("구성품 5종", len(r.components) == 5, len(r.components))
check("해석 정상", r.resolved is True)

bd = r.cost_breakdown()
check("자재비 13,200", round(bd["자재"]) == 13200, bd)
check("노무비 37,500", round(bd["노무"]) == 37500, bd)
check("장비비 4,000", round(bd["장비"]) == 4000, bd)
check("비목 합 = 단가", round(sum(bd.values())) == r.unit_price, bd)

print("\n=== 할증률 적용 ===")
pipe = next(c for c in r.components if c["공종명"] == "백강관")
check("할증 5% → 소요량 1.05", abs(pipe["소요량"] - 1.05) < 1e-9, pipe["소요량"])
check("할증 반영 금액 12,600", round(pipe["금액"]) == 12600, pipe["금액"])
check("할증 근거 문구", "할증 5%" in pipe["산출근거"], pipe["산출근거"])

print("\n=== 중첩 세트 ===")
n = resolutions["배관 조립일체"]
# 하위 54,700×2 = 109,400 + 엘보 3,000 = 112,400
check("중첩 단가 112,400원", n.unit_price == 112400, n.unit_price)
check("중첩 전개 구성품 6종", len(n.components) == 6, len(n.components))
check("하위 구성품 깊이 2", any(c["전개깊이"] == 2 for c in n.components))
nested_pipe = next(c for c in n.components if c["공종명"] == "백강관")
check("하위 소요량 배수 적용(1.05×2=2.1)", abs(nested_pipe["소요량"] - 2.1) < 1e-9,
      nested_pipe["소요량"])

print("\n=== 오류 탐지 ===")
cyc = resolutions["순환A"]
check("순환 참조 탐지", cyc.resolved is False)
check("순환 경로 표시", any("순환 참조" in i.message for i in cyc.issues),
      [i.message for i in cyc.issues])
miss = resolutions["누락포함"]
check("마스터 단가 누락 오류", miss.resolved is False and
      any("단가 없음" in i.message for i in miss.issues))
zero = resolutions["단가0"]
check("단가 0원 주의 경고", any("0원" in i.message for i in zero.issues))
check("미정의 세트 오류", boq.resolve_set("없는세트", set_index, price_index).resolved is False)

report = boq.validate(resolutions)
check("검증 리포트 생성", not report.empty and set(report.columns) ==
      {"수준", "세트명", "대상", "내용"}, list(report.columns))
check("오류/주의 구분", set(report["수준"].unique()) <= {"오류", "주의"},
      report["수준"].unique())

print("\n=== 내역서 전개 ===")
EST = pd.DataFrame([
    {"구분": "세트", "공종명": "소화배관 설치(50A)", "규격": "", "단위": "m",
     "단가": 0, "수량": 100, "합계": 0, "시작일": "2026-08-01", "종료일": "2026-08-10"},
    {"구분": "자재", "공종명": "엘보", "규격": "50A", "단위": "EA",
     "단가": 3000, "수량": 20, "합계": 60000, "시작일": "", "종료일": ""},
])
exp, issues = boq.expand_estimate(EST, set_index, price_index, mode="explode")
check("세트 1행 → 구성품 5행 전개", len(exp) == 6, len(exp))
check("세트 구분이 사라짐", "세트" not in exp["구분"].tolist(), exp["구분"].tolist())
check("전개 총액 = 54,700×100 + 60,000",
      int(config.to_number_series(exp["합계"]).sum()) == 5470000 + 60000,
      int(config.to_number_series(exp["합계"]).sum()))

groups = config.cost_group_series(exp)
amt = config.to_number_series(exp["합계"])
check("직접노무비 3,750,000 확보", int(amt[groups == "노무"].sum()) == 3750000,
      int(amt[groups == "노무"].sum()))
check("장비비 400,000", int(amt[groups == "장비"].sum()) == 400000)
check("추적 컬럼 존재", all(c in exp.columns for c in boq.TRACE_COLUMNS))
check("상위세트 기록", (exp["상위세트"] == "소화배관 설치(50A)").sum() == 5)

price_mode, _ = boq.expand_estimate(EST, set_index, price_index, mode="price")
check("price 모드는 1행 유지", len(price_mode) == 2, len(price_mode))
check("price 모드 단가 자동 산출",
      int(config.to_number_series(price_mode["단가"]).iloc[0]) == 54700)

bad = pd.DataFrame([{"구분": "세트", "공종명": "순환A", "규격": "", "단위": "식",
                     "단가": 999, "수량": 1, "합계": 999}])
kept, bad_issues = boq.expand_estimate(bad, set_index, price_index)
check("해석 실패 시 원본 행 보존", len(kept) == 1 and int(config.to_number_series(
    kept["합계"]).iloc[0]) == 999)
check("실패 경고 문구 표시", "실패" in str(kept["산출근거"].iloc[0]))

print("\n=== 일위대가표 / 소계 ===")
tbl = boq.build_ilwidaega_table(resolutions, only=["소화배관 설치(50A)"])
check("호표 표기", tbl["호표"].iloc[0] == "제1호표", tbl["호표"].iloc[0])
check("머리 + 구성 5 + 계 = 7행", len(tbl) == 7, len(tbl))
check("계 행 금액 = 단가", int(tbl["금액"].iloc[-1]) == 54700)
check("계 행에 비목 구성 표기", "노무" in str(tbl["비고"].iloc[-1]), tbl["비고"].iloc[-1])

sub = boq.insert_subtotals(exp, group_col="구분")
check("소계 행 삽입", (sub["공종명"].astype(str).str.startswith("▶")).sum() >= 2)
check("총계 행 생성", "■ 직접공사비 합계" in sub["공종명"].astype(str).tolist())
grand = int(config.to_number_series(
    sub[sub["공종명"] == "■ 직접공사비 합계"]["합계"]).iloc[0])
check("총계 = 전개 총액", grand == 5530000, grand)

print("\n=== 요약표 ===")
smry = boq.summarize(resolutions)
check("세트별 요약 생성", len(smry) == 6, len(smry))
row = smry[smry["세트명"] == "소화배관 설치(50A)"].iloc[0]
check("요약 단가 일치", int(row["산출단가"]) == 54700)
check("요약 노무비 일치", int(row["노무비"]) == 37500)
check("이상 세트 상태 표기",
      set(smry[smry["세트명"].isin(["순환A", "누락포함"])]["상태"]) == {"확인필요"})
check("양식 예시 제공", len(boq.sample_set_sheet()) == 5 and
      list(boq.sample_set_sheet().columns) == boq.SET_COLUMNS)

print("\n=== 원가계산 정확도 개선 확인 ===")
# 저장소의 패치본 원가계산기를 그대로 사용한다.
# (구 버전은 구분 == '자재' 정확 일치 버그로 금액이 누락되므로 패치본이 필수)
import logic_calculator as lc


def total_of(df):
    rows = lc.calculate_cost_summary(df, config.DEFAULT_RATES)
    return int(next(r for r in rows if "총 공사예정금액" in r["비목"])["금액(원)"].replace(",", ""))


lump = pd.DataFrame([{"구분": "자재", "공종명": "세트", "합계": 5470000}])
check("전개 후 도급액이 뭉친 계상보다 큼", total_of(exp) > total_of(lump),
      (total_of(exp), total_of(lump)))
gap = total_of(exp) - total_of(lump)
print(f"       └ 세트 100m 기준 도급액 차이: {gap:+,}원")

print("\n" + BAR * 58)
print(f"결과: {len(PASS)}건 통과 / {len(FAIL)}건 실패")
# 기계판독용 (ASCII 전용 → 어떤 콘솔 인코딩에서도 깨지지 않음)
print(f"PTS_RESULT PASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    print("실패: " + ", ".join(FAIL))
    sys.exit(1)
print("모든 검증을 통과했습니다.")
