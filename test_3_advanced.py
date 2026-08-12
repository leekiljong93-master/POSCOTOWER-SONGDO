# -*- coding: utf-8 -*-
"""
selftest_adv.py — 고도화 ②③④ 통합 검증
실행: python selftest_adv.py
"""

import datetime as _dt
import sys

import pandas as pd

import config
import logic_change as chg
import logic_schedule as sch
import logic_takeoff as tko

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
    ok = bool(cond)
    (PASS if ok else FAIL).append(name)
    suffix = ""
    if not ok:
        text = str(detail).strip()
        if text:
            suffix = f"  → {text}"
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")


# ═══════════════════════════════════════════════════════════
# ② 수량산출서
# ═══════════════════════════════════════════════════════════
print("=== ② 산출식 파서 (eval 미사용) ===")
check("단순 곱셈", tko.eval_formula("12.5 × 8.4") == 105.0)
check("괄호 우선순위", tko.eval_formula("(15 + 8) * 2 * 2.7") == 124.2)
check("사칙 혼합", tko.eval_formula("10 + 2 * 3") == 16.0)
check("나눗셈", tko.eval_formula("100 / 4") == 25.0)
check("콤마 천단위", tko.eval_formula("1,200 × 2") == 2400.0)
check("÷ 기호", tko.eval_formula("50 ÷ 2") == 25.0)
check("x 기호", tko.eval_formula("3 x 4") == 12.0)
check("단항 마이너스", tko.eval_formula("-5 + 8") == 3.0)
check("중첩 괄호", tko.eval_formula("((2+3)*(4-1))") == 15.0)

for bad, label in [("import os", "코드 삽입 차단"),
                   ("__import__('os')", "던더 차단"),
                   ("1+", "불완전 식 거부"),
                   ("(1+2", "괄호 불일치 거부"),
                   ("5/0", "0 나눗셈 거부"),
                   ("", "빈 식 거부")]:
    try:
        tko.eval_formula(bad)
        check(label, False, f"'{bad}' 가 통과됨")
    except tko.FormulaError:
        check(label, True)

print("\n=== ② 수량 산출 및 집계 ===")
TAKEOFF = pd.DataFrame([
    {"위치": "지하1층", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
     "산출식": "12.5 × 8.4", "가로": "", "세로": "", "높이": "", "개소": "",
     "공제": "", "비고": "기계실"},
    {"위치": "지하1층", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
     "산출식": "", "가로": "3.2", "세로": "2.1", "높이": "", "개소": "2",
     "공제": "", "비고": "치수 방식"},
    {"위치": "지하1층", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
     "산출식": "1.2 × 0.9", "가로": "", "세로": "", "높이": "", "개소": "",
     "공제": "공제", "비고": "개구부"},
    {"위치": "1층", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
     "산출식": "20 × 10", "가로": "", "세로": "", "높이": "", "개소": "",
     "공제": "", "비고": ""},
    {"위치": "1층", "공종명": "벽체 도장", "규격": "수성 2회", "단위": "m2",
     "산출식": "잘못된식!!", "가로": "", "세로": "", "높이": "", "개소": "",
     "공제": "", "비고": "오류 유발"},
])
computed, tko_issues = tko.compute_takeoff(TAKEOFF)

check("치수 자동 조립 (3.2×2.1×2=13.44)",
      abs(computed.loc[1, "산출수량"] - 13.44) < 1e-9, computed.loc[1, "산출수량"])
check("치수 산출식 문자열 생성", computed.loc[1, "적용식"] == "3.2 × 2.1 × 2",
      computed.loc[1, "적용식"])
check("공제 행은 음수", computed.loc[2, "산출수량"] < 0, computed.loc[2, "산출수량"])
check("공제 표기", computed.loc[2, "공제구분"] == "공제")
check("산출식 오류 시 0 처리", computed.loc[4, "산출수량"] == 0)
check("산출식 오류 경고 발생",
      any(i.level == "error" and "산출식 오류" in i.message for i in tko_issues))
check("오류 행도 보존", len(computed) == 5, len(computed))

summary = tko.aggregate(computed)
waterproof = summary[summary["공종명"] == "바닥 방수"].iloc[0]
# 105 + 13.44 + 200 = 318.44, 공제 1.08 → 순 317.36
check("집계 산출수량 318.44", abs(waterproof["산출수량"] - 318.44) < 0.01,
      waterproof["산출수량"])
check("집계 공제수량 -1.08", abs(waterproof["공제수량"] + 1.08) < 0.01,
      waterproof["공제수량"])
check("순수량 317.36", abs(waterproof["순수량"] - 317.36) < 0.01, waterproof["순수량"])
check("산출건수 4건", int(waterproof["산출건수"]) == 4, waterproof["산출건수"])

pivot = tko.pivot_by_location(computed)
check("층별 피벗 생성", "지하1층" in pivot.columns and "1층" in pivot.columns,
      list(pivot.columns))
wp_row = pivot[pivot["항목"].str.contains("바닥 방수")].iloc[0]
check("지하1층 물량 117.36", abs(wp_row["지하1층"] - 117.36) < 0.01, wp_row["지하1층"])
check("1층 물량 200", abs(wp_row["1층"] - 200.0) < 0.01, wp_row["1층"])

print("\n=== ② 내역서 연계 ===")
EST = pd.DataFrame([
    {"구분": "자재", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
     "단가": 25000, "수량": 999, "합계": 0},
    {"구분": "자재", "공종명": "미등록 항목", "규격": "", "단위": "EA",
     "단가": 1000, "수량": 5, "합계": 5000},
])
applied, apply_issues = tko.apply_to_estimate(EST, computed)
check("산출 수량으로 대체", abs(applied.loc[0, "수량"] - 317.36) < 0.01,
      applied.loc[0, "수량"])
check("합계 재계산", applied.loc[0, "합계"] == int(round(317.36 * 25000)),
      applied.loc[0, "합계"])
check("수량 출처 표기", applied.loc[0, "수량출처"] == "수량산출서")
check("미매칭 항목 기존 수량 유지", applied.loc[1, "수량"] == 5)
check("미매칭 출처 표기", applied.loc[1, "수량출처"] == "직접입력")
check("미사용 산출항목 경고",
      any("내역서에 없는" in i.message for i in apply_issues))

report = tko.build_takeoff_report(computed)
check("산출서 소계 행", (report["공종명"].str.startswith("▶")).sum() >= 2)
check("산출서 총계 행", "■ 총 산출 합계" in report["공종명"].tolist())
check("검증 리포트 생성",
      set(tko.validate(tko_issues).columns) == {"수준", "행", "대상", "내용"})
check("양식 예시 4행", len(tko.sample_takeoff_sheet()) == 4)

# ═══════════════════════════════════════════════════════════
# ③ 공정표
# ═══════════════════════════════════════════════════════════
print("\n=== ③ 영업일 달력 ===")
hol = sch.default_holidays()
check("2026 공휴일 사전 생성", len(hol) >= 20, len(hol))
check("추석 9/25 포함", _dt.date(2026, 9, 25) in hol)
check("상충 항목 제외 옵션",
      len(sch.default_holidays(include_uncertain=False)) < len(hol))
check("검증필요 목록 제공", len(sch.uncertain_holidays()) >= 4,
      len(sch.uncertain_holidays()))

cal = sch.WorkCalendar(_dt.date(2026, 8, 3), holidays=hol)
check("월요일은 영업일", cal.is_workday(_dt.date(2026, 8, 3)))
check("토요일 제외", not cal.is_workday(_dt.date(2026, 8, 8)))
check("일요일 제외", not cal.is_workday(_dt.date(2026, 8, 9)))
check("광복절 대체(8/17) 제외", not cal.is_workday(_dt.date(2026, 8, 17)))
check("8/3~8/7 영업일 5일",
      cal.count_between(_dt.date(2026, 8, 3), _dt.date(2026, 8, 7)) == 5)
# 8/10~8/14 (5일) + 8/17 대체공휴일 제외 → 8/18,19,20,21 = 4일
check("8/10~8/21 영업일 9일",
      cal.count_between(_dt.date(2026, 8, 10), _dt.date(2026, 8, 21)) == 9,
      cal.count_between(_dt.date(2026, 8, 10), _dt.date(2026, 8, 21)))
check("토요일 근무 옵션",
      sch.WorkCalendar(_dt.date(2026, 8, 3), holidays=hol, work_saturday=True)
      .is_workday(_dt.date(2026, 8, 8)))
check("휴무일 → 다음 영업일 보정",
      cal.date_of(cal.ordinal_of(_dt.date(2026, 8, 8))) == _dt.date(2026, 8, 10))

print("\n=== ③ 선행공정 표기 파서 ===")
rels, errs = sch.parse_predecessors("A10")
check("기본 FS", rels[0].rel_type == "FS" and rels[0].lag == 0 and not errs)
rels, _ = sch.parse_predecessors("A20FS+2")
check("FS+2 지연", rels[0].rel_type == "FS" and rels[0].lag == 2)
rels, _ = sch.parse_predecessors("A30SS")
check("SS 관계", rels[0].rel_type == "SS")
rels, _ = sch.parse_predecessors("A40FF-1")
check("FF-1 선행", rels[0].rel_type == "FF" and rels[0].lag == -1)
rels, _ = sch.parse_predecessors("A50+3")
check("FS 생략형", rels[0].rel_type == "FS" and rels[0].lag == 3)
rels, _ = sch.parse_predecessors("A10, A20SS+1")
check("복수 선행", len(rels) == 2 and rels[1].lag == 1)
check("빈 값 처리", sch.parse_predecessors("") == ([], []))

print("\n=== ③ CPM 계산 ===")
result = sch.compute_schedule(sch.sample_schedule_sheet(),
                              project_start="2026-08-03", holidays=hol)
table, summary = result["table"], result["summary"]
check("6개 활동 계산", len(table) == 6, len(table))
check("착수일 8/3", summary["착수일"] == _dt.date(2026, 8, 3), summary["착수일"])

a10 = table[table["ID"] == "A10"].iloc[0]
check("A10 8/3~8/5 (3영업일)",
      a10["시작일"].date() == _dt.date(2026, 8, 3) and
      a10["종료일"].date() == _dt.date(2026, 8, 5),
      (a10["시작일"], a10["종료일"]))

a20 = table[table["ID"] == "A20"].iloc[0]
check("A20 선행 종료 후 8/6 착수", a20["시작일"].date() == _dt.date(2026, 8, 6),
      a20["시작일"])
# 8/6,7 (2) + 주말 + 8/10,11,12 (3) = 5영업일 → 8/12 종료
check("A20 8/12 종료 (주말 제외)", a20["종료일"].date() == _dt.date(2026, 8, 12),
      a20["종료일"])

a30 = table[table["ID"] == "A30"].iloc[0]
# A20 종료 후 FS+1 → 8/13 건너뛰고 8/14 착수
check("A30 FS+1 반영 8/14 착수", a30["시작일"].date() == _dt.date(2026, 8, 14),
      a30["시작일"])

m99 = table[table["ID"] == "M99"].iloc[0]
check("마일스톤 공기 0", m99["공기"] == 0)
check("마일스톤 시작=종료", m99["시작일"] == m99["종료일"])
check("마일스톤 표기", m99["마일스톤"] == "◆")

check("주공정선 존재", summary["주공정활동"] >= 1, summary["주공정활동"])
check("주공정 여유일 0",
      (table[table["주공정"] == "★"]["여유일"] == 0).all())
check("비주공정 여유일 > 0",
      (table[table["주공정"] == ""]["여유일"] > 0).all()
      if (table["주공정"] == "").any() else True)
check("영업일 공기 산출", summary["총공기(영업일)"] > 0, summary["총공기(영업일)"])
check("달력일 > 영업일 (휴일 반영)",
      summary["총공기(달력일)"] > summary["총공기(영업일)"],
      (summary["총공기(달력일)"], summary["총공기(영업일)"]))

print("\n=== ③ 오류 탐지 ===")
CYCLE = pd.DataFrame([
    {"activity_id": "X1", "공종명": "X1", "공기": 2, "선행공정": "X2"},
    {"activity_id": "X2", "공종명": "X2", "공기": 2, "선행공정": "X1"},
])
cyc = sch.compute_schedule(CYCLE, project_start="2026-08-03", holidays=hol)
check("순환 참조 탐지",
      any("순환 참조" in i.message for i in cyc["issues"]),
      [i.message for i in cyc["issues"]])
check("순환 시 입력 보존", len(cyc["table"]) == 2)

MISSING = pd.DataFrame([
    {"activity_id": "Y1", "공종명": "Y1", "공기": 2, "선행공정": "없는공정"},
])
miss = sch.compute_schedule(MISSING, project_start="2026-08-03", holidays=hol)
check("없는 선행 참조 경고",
      any("목록에 없습니다" in i.message for i in miss["issues"]))
check("없는 선행 무시 후 계산 진행", len(miss["table"]) == 1)

DUP = pd.DataFrame([
    {"activity_id": "Z1", "공종명": "a", "공기": 1, "선행공정": ""},
    {"activity_id": "Z1", "공종명": "b", "공기": 1, "선행공정": ""},
])
dup = sch.compute_schedule(DUP, project_start="2026-08-03", holidays=hol)
check("ID 중복 경고", any("중복" in i.message for i in dup["issues"]))

late = sch.compute_schedule(sch.sample_schedule_sheet(), project_start="2026-08-03",
                            holidays=hol, deadline="2026-08-20")
check("목표 준공일 초과 경고",
      any("초과" in i.message for i in late["issues"]),
      [i.message for i in late["issues"]])

print("\n=== ③ S-Curve / 주공정표 ===")
AMOUNTS = pd.DataFrame([
    {"공종명": "가설 및 준비", "합계": 3_000_000},
    {"공종명": "기존 배관 철거", "합계": 5_000_000},
    {"공종명": "소화배관 설치", "합계": 30_000_000},
    {"공종명": "도장", "합계": 4_000_000},
    {"공종명": "수압시험", "합계": 2_000_000},
])
res2 = sch.compute_schedule(sch.sample_schedule_sheet(), project_start="2026-08-03",
                            holidays=hol, df_amounts=AMOUNTS)
check("금액 연계", res2["table"]["금액"].sum() == 44_000_000,
      res2["table"]["금액"].sum())

curve = sch.build_s_curve(res2["table"], res2["calendar"], freq="W")
check("S-Curve 생성", not curve.empty and "누적진도율(%)" in curve.columns)
check("최종 진도율 100%", abs(curve["누적진도율(%)"].iloc[-1] - 100.0) < 0.1,
      curve["누적진도율(%)"].iloc[-1])
check("누적 단조 증가", (curve["누적금액"].diff().dropna() >= 0).all())
check("누적금액 = 총액", curve["누적금액"].iloc[-1] == 44_000_000,
      curve["누적금액"].iloc[-1])

cp = sch.critical_path_table(res2["table"])
check("주공정표 추출", not cp.empty and (cp["주공정"] == "★").all())
check("일정 검증표 생성",
      set(sch.validate(res2["issues"]).columns) == {"수준", "대상", "내용"})

# ═══════════════════════════════════════════════════════════
# ④ 설계변경 대비표
# ═══════════════════════════════════════════════════════════
print("\n=== ④ 변경 유형 판정 ===")
check("신규", chg.classify(0, 0, 10, 100, exists_before=False, exists_after=True)
      == chg.T_NEW)
check("삭제", chg.classify(10, 100, 0, 0, exists_before=True, exists_after=False)
      == chg.T_DELETED)
check("수량증감", chg.classify(10, 100, 15, 100, exists_before=True, exists_after=True)
      == chg.T_QTY)
check("단가변경", chg.classify(10, 100, 10, 120, exists_before=True, exists_after=True)
      == chg.T_PRICE)
check("복합변경", chg.classify(10, 100, 15, 120, exists_before=True, exists_after=True)
      == chg.T_BOTH)
check("변동없음", chg.classify(10, 100, 10, 100, exists_before=True, exists_after=True)
      == chg.T_SAME)
check("반올림 오차는 변동없음",
      chg.classify(10, 100, 10.0000001, 100.2, exists_before=True, exists_after=True)
      == chg.T_SAME)

print("\n=== ④ 대비표 생성 ===")
BEFORE = pd.DataFrame([
    {"구분": "자재", "공종명": "소화배관", "규격": "50A", "단위": "m",
     "단가": 12000, "수량": 100, "합계": 1_200_000},
    {"구분": "노무", "공종명": "배관공", "규격": "", "단위": "인",
     "단가": 250000, "수량": 12, "합계": 3_000_000},
    {"구분": "자재", "공종명": "철거 폐기물", "규격": "", "단위": "ton",
     "단가": 80000, "수량": 5, "합계": 400_000},
    {"구분": "자재", "공종명": "행거", "규격": "", "단위": "EA",
     "단가": 1500, "수량": 40, "합계": 60_000},
])
AFTER = pd.DataFrame([
    {"구분": "자재비", "공종명": "소화배관", "규격": "50A", "단위": "m",   # 표기 혼용
     "단가": 12000, "수량": 130, "합계": 1_560_000},                      # 수량증감
    {"구분": "노무", "공종명": "배관공", "규격": "", "단위": "인",
     "단가": 265000, "수량": 15, "합계": 3_975_000},                      # 복합변경
    {"구분": "자재", "공종명": "행거", "규격": "", "단위": "EA",
     "단가": 1500, "수량": 40, "합계": 60_000},                           # 변동없음
    {"구분": "장비", "공종명": "고소작업대", "규격": "", "단위": "일",
     "단가": 150000, "수량": 6, "합계": 900_000},                         # 신규
])
REASONS = pd.DataFrame([
    {"공종명": "소화배관", "규격": "50A", "변경사유": "노출배관 변경",
     "요청자": "시설팀", "승인일": "2026-08-05"},
    {"공종명": "고소작업대", "규격": "", "변경사유": "고소작업 안전 조치",
     "요청자": "안전TF", "승인일": "2026-08-06"},
])
cmp_table, cmp_issues = chg.compare(BEFORE, AFTER, df_reasons=REASONS)

check("전체 5행 (당초4 + 신규1)", len(cmp_table) == 5, len(cmp_table))
types = dict(zip(cmp_table["공종명"], cmp_table["변경유형"]))
check("구분 표기 혼용 흡수(자재비→자재)", types["소화배관"] == chg.T_QTY, types)
check("복합변경 판정", types["배관공"] == chg.T_BOTH, types)
check("삭제 항목 탐지", types["철거 폐기물"] == chg.T_DELETED, types)
check("신규 항목 탐지", types["고소작업대"] == chg.T_NEW, types)
check("변동없음 판정", types["행거"] == chg.T_SAME, types)

pipe = cmp_table[cmp_table["공종명"] == "소화배관"].iloc[0]
check("증감수량 +30", pipe["증감수량"] == 30, pipe["증감수량"])
check("증감금액 +360,000", pipe["증감금액"] == 360_000, pipe["증감금액"])
check("증감률 +30%", abs(pipe["증감률(%)"] - 30.0) < 0.01, pipe["증감률(%)"])
check("변경사유 병합", "노출배관" in pipe["변경사유"], pipe["변경사유"])
check("요청자 표기", "시설팀" in pipe["변경사유"], pipe["변경사유"])

deleted = cmp_table[cmp_table["공종명"] == "철거 폐기물"].iloc[0]
check("삭제 항목 증감액 음수", deleted["증감금액"] == -400_000, deleted["증감금액"])
check("삭제 항목 변경금액 0", deleted["변경금액"] == 0)
new_item = cmp_table[cmp_table["공종명"] == "고소작업대"].iloc[0]
check("신규 항목 당초금액 0", new_item["당초금액"] == 0)
check("신규 항목 증감률 None", pd.isna(new_item["증감률(%)"]))
check("사유 없는 변경 경고",
      any("변경 사유가 없습니다" in i.message for i in cmp_issues))

print("\n=== ④ 총액 검증 및 요약 ===")
total_before = int(cmp_table["당초금액"].sum())
total_after = int(cmp_table["변경금액"].sum())
total_delta = int(cmp_table["증감금액"].sum())
check("당초 총액 4,660,000", total_before == 4_660_000, total_before)
check("변경 총액 6,495,000", total_after == 6_495_000, total_after)
check("증감 합계 = 총액 차이", total_delta == total_after - total_before,
      (total_delta, total_after - total_before))
check("총액 검증 오류 없음",
      not any(i.level == "error" for i in cmp_issues),
      [i.message for i in cmp_issues if i.level == "error"])

by_type = chg.summarize_by_type(cmp_table)
check("유형별 요약 + 합계행", "■ 합계" in by_type["변경유형"].tolist())
check("유형별 건수 합 = 5",
      int(by_type[by_type["변경유형"] == "■ 합계"]["건수"].iloc[0]) == 5)

by_group = chg.summarize_by_cost_group(cmp_table)
check("비목별 요약 생성", "■ 직접공사비 계" in by_group["비목"].tolist())
labor = by_group[by_group["비목"] == "노무"].iloc[0]
check("노무 증감 +975,000", labor["증감금액"] == 975_000, labor["증감금액"])

no_same, _ = chg.compare(BEFORE, AFTER, df_reasons=REASONS, include_same=False)
check("변동없음 제외 옵션", len(no_same) == 4 and
      chg.T_SAME not in no_same["변경유형"].tolist(), len(no_same))

print("\n=== ④ 도급액 비교 / 결재 서식 ===")
# 저장소의 패치본 원가계산기를 그대로 사용한다.
# (구 버전은 구분 == '자재' 정확 일치 버그로 금액이 누락되므로 패치본이 필수)
import logic_calculator as lc

contract = chg.compare_contract_price(BEFORE, AFTER, config.DEFAULT_RATES,
                                     lc.calculate_cost_summary)
check("도급액 비교표 생성", not contract.empty)
total_row = contract[contract["비목"].str.contains("총 공사예정금액")].iloc[0]
check("도급액 증감 산출", total_row["증감"] != 0, total_row["증감"])
labor_row = contract[contract["비목"].str.contains("간접노무비")].iloc[0]
check("간접노무비도 증가 반영", labor_row["증감"] > 0, labor_row["증감"])
print(f"       └ 도급액: {total_row['당초']:,} → {total_row['변경']:,} "
      f"({total_row['증감']:+,}원)")

report4 = chg.build_change_report(cmp_table)
check("대비표 소계 행", (report4["공종명"].str.startswith("▶")).sum() >= 2)
check("대비표 총계 행", "■ 직접공사비 합계" in report4["공종명"].tolist())
grand = report4[report4["공종명"] == "■ 직접공사비 합계"].iloc[0]
check("총계 증감액 일치", int(grand["증감금액"]) == total_delta,
      (grand["증감금액"], total_delta))

execsum = chg.build_executive_summary(cmp_table, project_name="포스코타워-송도 시험",
                                     contract_table=contract)
check("임원요약 생성", not execsum.empty)
check("증감액 ▲ 표기",
      any("▲" in str(v) for v in execsum["내용"].tolist()),
      execsum["내용"].tolist()[:5])
check("주요 증액 항목 포함",
      any("주요 증액" == v for v in execsum["항목"].tolist()))
check("도급액 증감 포함",
      any("도급액" in str(v) for v in execsum["항목"].tolist()))
check("변경사유 시트 예시", len(chg.sample_reason_sheet()) == 2)

print("\n" + BAR * 58)
print(f"결과: {len(PASS)}건 통과 / {len(FAIL)}건 실패")
# 기계판독용 (ASCII 전용 → 어떤 콘솔 인코딩에서도 깨지지 않음)
print(f"PTS_RESULT PASS={len(PASS)} FAIL={len(FAIL)}")
if FAIL:
    print("실패: " + ", ".join(FAIL))
    sys.exit(1)
print("모든 검증을 통과했습니다.")
