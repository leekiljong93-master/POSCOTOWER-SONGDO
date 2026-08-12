# -*- coding: utf-8 -*-
"""
logic_takeoff.py
─────────────────────────────────────────────────────────────
수량산출서 엔진 — 고도화 ②

배경
  일위대가로 '단가 근거'는 확보했으나 '수량 근거'가 없었다.
  현재 구조는 내역서에 수량을 손으로 적는 방식이라, 감사·검증 요청 시
  "이 300m² 는 어디서 나온 숫자인가"에 답할 문서가 남지 않는다.
  실무에서 가장 먼저 요구되는 문서가 수량산출서(산출근거서)다.

이 모듈이 하는 일
  1. '수량산출' 시트로 부위·위치별 산출식을 관리
  2. 산출식 문자열을 안전하게 계산 (eval 미사용 — 자체 재귀하강 파서)
  3. 치수 컬럼(가로·세로·높이·개소)만 채워도 산출식 자동 생성
  4. 공제(개구부 등) 행을 음수로 처리
  5. 공종·규격별 집계 → 내역서 수량으로 연계
  6. 층별/구역별 교차집계(피벗) → 층별 물량 확인
  7. 산출식 오류·음수 수량·단위 불일치 검증

설계 원칙
  · eval / exec 를 절대 쓰지 않는다. 스프레드시트 입력은 신뢰할 수 없는 입력이다.
  · 반올림 자리수를 상수로 노출한다. (기관별 기준 상이)
  · 검증 실패 행은 버리지 않고 0으로 두고 경고한다. (데이터 소실 방지)

의존: config, pandas
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

import config

log = config.get_logger("takeoff")

# ═══════════════════════════════════════════════════════════
# 0. 스키마 및 상수
# ═══════════════════════════════════════════════════════════
TAKEOFF_SHEET = "수량산출"
TAKEOFF_COLUMNS = [
    "위치", "공종명", "규격", "단위", "산출식",
    "가로", "세로", "높이", "개소", "공제", "비고",
]

DIM_COLUMNS = ["가로", "세로", "높이", "개소"]

QTY_DECIMALS = 3          # 산출 수량 반올림 자리수
SUM_DECIMALS = 2          # 집계 수량 반올림 자리수

# 공제 여부로 인정하는 표기
DEDUCT_TOKENS = ("공제", "차감", "감", "-", "y", "yes", "true", "o", "ㅇ", "1")

_EMPTY_TOKENS = ("", "-", "nan", "none", "null")

# 산출식에 허용되는 문자 (이 외 문자가 있으면 즉시 거부)
_ALLOWED_FORMULA = re.compile(r"^[0-9\.\s\+\-\*/×÷x\(\)]*$", re.IGNORECASE)
_NUMBER_RE = re.compile(r"\d+(?:\.\d+)?")


def _norm_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_TOKENS else text


def _is_deduction(value) -> bool:
    text = _norm_text(value).lower()
    return text in DEDUCT_TOKENS if text else False


# ═══════════════════════════════════════════════════════════
# 1. 안전한 산출식 파서 (eval 미사용)
# ═══════════════════════════════════════════════════════════
class FormulaError(ValueError):
    """산출식 해석 실패."""


def _tokenize(formula: str) -> list:
    """산출식을 토큰 목록으로 분해한다.

    허용: 숫자(소수 포함), + - * / ( ), 그리고 × ÷ x 를 각각 * / * 로 정규화
    콤마는 천단위 구분으로 보아 제거한다.
    """
    text = str(formula).replace(",", "")
    if not _ALLOWED_FORMULA.match(text):
        bad = sorted({ch for ch in text if not _ALLOWED_FORMULA.match(ch)})
        raise FormulaError(f"허용되지 않은 문자: {' '.join(bad)}")

    text = (text.replace("×", "*").replace("÷", "/")
                .replace("X", "*").replace("x", "*"))

    tokens: list = []
    i = 0
    while i < len(text):
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        match = _NUMBER_RE.match(text, i)
        if match:
            tokens.append(float(match.group()))
            i = match.end()
            continue
        if ch in "+-*/()":
            tokens.append(ch)
            i += 1
            continue
        raise FormulaError(f"해석할 수 없는 문자 '{ch}'")
    return tokens


class _Parser:
    """재귀하강 파서.

    expr   := term (('+'|'-') term)*
    term   := factor (('*'|'/') factor)*
    factor := ('+'|'-')? (number | '(' expr ')')
    """

    def __init__(self, tokens: list):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.pos += 1
        return token

    def parse(self) -> float:
        if not self.tokens:
            raise FormulaError("빈 산출식")
        value = self.expr()
        if self.pos != len(self.tokens):
            raise FormulaError(f"'{self.peek()}' 이후를 해석할 수 없음")
        return value

    def expr(self) -> float:
        value = self.term()
        while self.peek() in ("+", "-"):
            op = self.take()
            right = self.term()
            value = value + right if op == "+" else value - right
        return value

    def term(self) -> float:
        value = self.factor()
        while self.peek() in ("*", "/"):
            op = self.take()
            right = self.factor()
            if op == "*":
                value *= right
            else:
                if right == 0:
                    raise FormulaError("0 으로 나눌 수 없음")
                value /= right
        return value

    def factor(self) -> float:
        token = self.peek()
        if token == "+":
            self.take()
            return self.factor()
        if token == "-":
            self.take()
            return -self.factor()
        if token == "(":
            self.take()
            value = self.expr()
            if self.take() != ")":
                raise FormulaError("닫는 괄호가 없음")
            return value
        if isinstance(token, float):
            self.take()
            return token
        raise FormulaError("숫자가 와야 할 자리에 다른 토큰이 있음"
                           if token is not None else "산출식이 중간에 끝남")


def eval_formula(formula: str) -> float:
    """산출식 문자열을 계산한다. 실패 시 FormulaError."""
    return _Parser(_tokenize(formula)).parse()


def build_formula_from_dims(row) -> str:
    """치수 컬럼(가로·세로·높이·개소)에서 산출식을 조립한다.

    비어 있거나 0 인 항목은 제외한다. 모두 비면 빈 문자열.
    """
    parts = []
    for col in DIM_COLUMNS:
        raw = _norm_text(row.get(col))
        if not raw:
            continue
        value = config.to_number_series([raw]).iloc[0]
        if value == 0:
            continue
        parts.append(f"{value:g}")
    return " × ".join(parts)


# ═══════════════════════════════════════════════════════════
# 2. 결과 컨테이너
# ═══════════════════════════════════════════════════════════
@dataclass
class TakeoffIssue:
    level: str          # "error" | "warn"
    row_no: int
    target: str
    message: str

    def as_row(self) -> dict:
        return {"수준": "오류" if self.level == "error" else "주의",
                "행": self.row_no, "대상": self.target, "내용": self.message}


# ═══════════════════════════════════════════════════════════
# 3. 입력 정규화
# ═══════════════════════════════════════════════════════════
def empty_takeoff_sheet() -> pd.DataFrame:
    return pd.DataFrame(columns=TAKEOFF_COLUMNS)


def normalize_takeoff_sheet(df: pd.DataFrame | None) -> pd.DataFrame:
    """수량산출 시트를 표준 스키마로 정렬한다."""
    if df is None or df.empty:
        return empty_takeoff_sheet()

    out = df.copy().reset_index(drop=True)
    for col in TAKEOFF_COLUMNS:
        if col not in out.columns:
            out[col] = ""

    for col in ("위치", "공종명", "규격", "단위", "산출식", "공제", "비고"):
        out[col] = out[col].map(_norm_text)
    for col in DIM_COLUMNS:
        out[col] = out[col].map(_norm_text)

    out = out[out["공종명"] != ""]
    return out[TAKEOFF_COLUMNS].reset_index(drop=True)


# ═══════════════════════════════════════════════════════════
# 4. 수량 산출
# ═══════════════════════════════════════════════════════════
def compute_takeoff(df: pd.DataFrame | None) -> tuple[pd.DataFrame, list]:
    """산출식을 계산해 행별 수량을 채운다.

    반환: (산출 결과 DataFrame, 경고 목록)
      · '적용식'  : 실제 계산에 쓰인 식 (치수 자동 조립 결과 포함)
      · '산출수량': 부호가 적용된 수량 (공제 행은 음수)
      · '공제구분': "공제" 또는 ""
    """
    normalized = normalize_takeoff_sheet(df)
    if normalized.empty:
        empty = normalized.assign(적용식="", 산출수량=0.0, 공제구분="")
        return empty, []

    issues: list = []
    formulas: list = []
    quantities: list = []
    marks: list = []

    for idx, row in normalized.iterrows():
        row_no = idx + 2                      # 스프레드시트 행 번호(헤더 1행 가정)
        label = f"{row['공종명']}({row['위치'] or '위치미지정'})"

        formula = _norm_text(row["산출식"]) or build_formula_from_dims(row)
        deduct = _is_deduction(row["공제"])

        if not formula:
            issues.append(TakeoffIssue("error", row_no, label,
                                       "산출식과 치수가 모두 비어 있음"))
            formulas.append("")
            quantities.append(0.0)
            marks.append("공제" if deduct else "")
            continue

        try:
            value = eval_formula(formula)
        except FormulaError as exc:
            issues.append(TakeoffIssue("error", row_no, label,
                                       f"산출식 오류 — {exc} (입력: {formula})"))
            formulas.append(formula)
            quantities.append(0.0)
            marks.append("공제" if deduct else "")
            continue

        if value < 0:
            issues.append(TakeoffIssue("warn", row_no, label,
                                       f"산출 결과가 음수({value:g})입니다. 공제 행이라면 '공제' 열을 쓰세요."))
        elif value == 0:
            issues.append(TakeoffIssue("warn", row_no, label, "산출 수량이 0입니다."))

        if not _norm_text(row["단위"]):
            issues.append(TakeoffIssue("warn", row_no, label, "단위가 비어 있습니다."))

        signed = -abs(value) if deduct else value
        formulas.append(formula)
        quantities.append(round(signed, QTY_DECIMALS))
        marks.append("공제" if deduct else "")

    result = normalized.copy()
    result["적용식"] = formulas
    result["산출수량"] = quantities
    result["공제구분"] = marks
    return result, issues


# ═══════════════════════════════════════════════════════════
# 5. 집계
# ═══════════════════════════════════════════════════════════
def aggregate(df_computed: pd.DataFrame | None,
              *, keys: list | None = None) -> pd.DataFrame:
    """공종·규격·단위별로 수량을 합산한다. (공제는 음수로 반영)"""
    keys = keys or ["공종명", "규격", "단위"]
    if df_computed is None or df_computed.empty:
        return pd.DataFrame(columns=keys + ["산출수량", "공제수량", "순수량", "산출건수"])

    work = df_computed.copy()
    work["산출수량"] = config.to_number_series(work["산출수량"])
    for key in keys:
        if key not in work.columns:
            work[key] = ""
        work[key] = work[key].map(_norm_text)

    positive = work["산출수량"].clip(lower=0)
    negative = work["산출수량"].clip(upper=0)

    grouped = work.assign(_pos=positive, _neg=negative).groupby(keys, sort=False, dropna=False)
    summary = grouped.agg(산출수량=("_pos", "sum"),
                          공제수량=("_neg", "sum"),
                          산출건수=("산출수량", "size")).reset_index()
    summary["순수량"] = (summary["산출수량"] + summary["공제수량"]).round(SUM_DECIMALS)
    summary["산출수량"] = summary["산출수량"].round(SUM_DECIMALS)
    summary["공제수량"] = summary["공제수량"].round(SUM_DECIMALS)
    return summary[keys + ["산출수량", "공제수량", "순수량", "산출건수"]]


def pivot_by_location(df_computed: pd.DataFrame | None) -> pd.DataFrame:
    """층별/구역별 교차집계. 층별 물량 확인 및 보고용."""
    if df_computed is None or df_computed.empty:
        return pd.DataFrame()

    work = df_computed.copy()
    work["산출수량"] = config.to_number_series(work["산출수량"])
    work["위치"] = work["위치"].map(lambda v: _norm_text(v) or "미지정")
    work["항목"] = work.apply(
        lambda r: f"{r['공종명']}" + (f" ({r['규격']})" if _norm_text(r["규격"]) else ""), axis=1)

    table = pd.pivot_table(work, index="항목", columns="위치", values="산출수량",
                           aggfunc="sum", fill_value=0)
    table = table.round(SUM_DECIMALS)
    table["합계"] = table.sum(axis=1).round(SUM_DECIMALS)
    return table.reset_index()


# ═══════════════════════════════════════════════════════════
# 6. 내역서 연계
# ═══════════════════════════════════════════════════════════
def apply_to_estimate(df_estimate: pd.DataFrame | None,
                      df_computed: pd.DataFrame | None,
                      *, only_matched: bool = True) -> tuple[pd.DataFrame, list]:
    """산출 집계 수량을 내역서 '수량' 열에 반영한다.

    매칭 키: 공종명 + 규격 + 단위
    only_matched=True  : 산출서에 있는 항목만 갱신 (없는 항목은 손대지 않음)
    only_matched=False : 산출서에 없는 항목의 수량을 0으로 만들지 않고 경고만 남김
    """
    if df_estimate is None or df_estimate.empty:
        return (pd.DataFrame(columns=config.ESTIMATE_COLUMNS), [])

    summary = aggregate(df_computed)
    lookup = {}
    for _, row in summary.iterrows():
        key = (_norm_text(row["공종명"]), _norm_text(row["규격"]), _norm_text(row["단위"]))
        lookup[key] = float(row["순수량"])

    out = df_estimate.copy().reset_index(drop=True)
    out["단가"] = config.to_number_series(out.get("단가", 0))
    out["수량"] = config.to_number_series(out.get("수량", 0))

    issues: list = []
    applied = 0
    new_qty: list = []
    sources: list = []

    for idx, row in out.iterrows():
        key = (_norm_text(row.get("공종명")), _norm_text(row.get("규격")),
               _norm_text(row.get("단위")))
        if key in lookup:
            qty = lookup[key]
            if qty < 0:
                issues.append(TakeoffIssue("error", idx + 1, key[0],
                                           f"공제가 산출량을 초과해 순수량이 음수({qty:g})입니다."))
            new_qty.append(qty)
            sources.append("수량산출서")
            applied += 1
        else:
            new_qty.append(float(row["수량"]))
            sources.append("직접입력")
            if not only_matched:
                issues.append(TakeoffIssue("warn", idx + 1, key[0],
                                           "수량산출서에 해당 항목이 없어 기존 수량을 유지했습니다."))

    out["수량"] = new_qty
    out["수량출처"] = sources
    out["합계"] = (out["단가"] * out["수량"]).round(0).astype("int64")

    unused = set(lookup.keys()) - {
        (_norm_text(r.get("공종명")), _norm_text(r.get("규격")), _norm_text(r.get("단위")))
        for _, r in df_estimate.iterrows()}
    for key in sorted(unused):
        issues.append(TakeoffIssue("warn", 0, key[0],
                                   "산출서에는 있으나 내역서에 없는 항목입니다."))

    log.info("수량 반영: %d행 / 미사용 산출항목 %d건", applied, len(unused))
    return out, issues


# ═══════════════════════════════════════════════════════════
# 7. 산출서 서식 (엑셀 출력용)
# ═══════════════════════════════════════════════════════════
def build_takeoff_report(df_computed: pd.DataFrame | None) -> pd.DataFrame:
    """엑셀 '수량산출서' 시트용. 공종별 소계와 총계를 삽입한다."""
    if df_computed is None or df_computed.empty:
        return pd.DataFrame(columns=["위치", "공종명", "규격", "단위", "산출식", "수량", "비고"])

    work = df_computed.copy()
    work["산출수량"] = config.to_number_series(work["산출수량"])
    rows: list = []
    grand = 0.0

    for name, part in work.groupby("공종명", sort=False):
        for _, row in part.iterrows():
            rows.append({
                "위치": row["위치"], "공종명": row["공종명"], "규격": row["규격"],
                "단위": row["단위"], "산출식": row["적용식"],
                "수량": round(float(row["산출수량"]), QTY_DECIMALS),
                "비고": (row["비고"] + (" [공제]" if row["공제구분"] else "")).strip(),
            })
        subtotal = float(part["산출수량"].sum())
        grand += subtotal
        rows.append({"위치": "", "공종명": f"▶ {name} 계", "규격": "",
                     "단위": _norm_text(part.iloc[0]["단위"]), "산출식": "",
                     "수량": round(subtotal, SUM_DECIMALS), "비고": ""})

    rows.append({"위치": "", "공종명": "■ 총 산출 합계", "규격": "", "단위": "",
                 "산출식": "", "수량": round(grand, SUM_DECIMALS), "비고": "단위 혼재 주의"})
    return pd.DataFrame(rows, columns=["위치", "공종명", "규격", "단위", "산출식", "수량", "비고"])


def validate(issues: list) -> pd.DataFrame:
    """경고 목록을 표로 변환."""
    seen: set = set()
    rows: list = []
    for issue in issues or []:
        signature = (issue.level, issue.row_no, issue.target, issue.message)
        if signature in seen:
            continue
        seen.add(signature)
        rows.append(issue.as_row())
    return pd.DataFrame(rows, columns=["수준", "행", "대상", "내용"])


def sample_takeoff_sheet() -> pd.DataFrame:
    """작성 예시 (양식 다운로드용)."""
    return pd.DataFrame([
        {"위치": "지하1층", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
         "산출식": "12.5 × 8.4", "가로": "", "세로": "", "높이": "", "개소": "",
         "공제": "", "비고": "기계실"},
        {"위치": "지하1층", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
         "산출식": "", "가로": "3.2", "세로": "2.1", "높이": "", "개소": "2",
         "공제": "", "비고": "치수 입력 방식"},
        {"위치": "지하1층", "공종명": "바닥 방수", "규격": "우레탄 2mm", "단위": "m2",
         "산출식": "1.2 × 0.9", "가로": "", "세로": "", "높이": "", "개소": "",
         "공제": "공제", "비고": "집수정 개구부"},
        {"위치": "1층", "공종명": "벽체 도장", "규격": "수성 2회", "단위": "m2",
         "산출식": "(15.0 + 8.0) × 2 × 2.7", "가로": "", "세로": "", "높이": "",
         "개소": "", "공제": "", "비고": "둘레 × 층고"},
    ], columns=TAKEOFF_COLUMNS)
