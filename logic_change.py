# -*- coding: utf-8 -*-
"""
logic_change.py
─────────────────────────────────────────────────────────────
설계변경 대비표 엔진 — 고도화 ④

배경
  실무에서 설계변경은 피할 수 없고, 그때마다 손으로 '당초 vs 변경' 대비표를
  다시 만든다. 엑셀로 두 파일을 나란히 놓고 눈으로 비교하다 보니
  · 신규 추가 / 완전 삭제 항목을 빠뜨리기 쉽다
  · 수량만 바뀐 것과 단가까지 바뀐 것이 구분되지 않는다
  · 증감액 합계가 당초·변경 총액 차이와 맞는지 검증되지 않는다
  → 변경계약 결재 시 가장 많이 반송되는 지점이다.

이 모듈이 하는 일
  1. 당초·변경 내역서를 키(구분+공종명+규격+단위)로 자동 매칭
  2. 변경 유형 분류: 신규 / 삭제 / 수량증감 / 단가변경 / 복합변경 / 변동없음
  3. 항목별 증감 수량·증감액 산출 + 변경 사유 병합
  4. 비목별(자재·노무·장비) 증감 요약
  5. 총액 검증 — 당초 + 증감 = 변경 이 성립하는지 확인
  6. 원가계산서 기준 도급액 증감 비교 (제비율 반영)
  7. 결재용 대비표 서식 생성 (소계·총계 포함)

설계 원칙
  · 부동소수점 비교는 허용오차(tolerance)를 두고 판정한다.
  · 매칭 실패를 '변동없음'으로 흘리지 않는다. 반드시 신규/삭제로 드러낸다.
  · 증감률 계산 시 분모 0(신규 항목)을 안전하게 처리한다.

의존: config, pandas
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

import config

log = config.get_logger("change")

# ═══════════════════════════════════════════════════════════
# 0. 스키마 및 상수
# ═══════════════════════════════════════════════════════════
REASON_SHEET = "변경사유"
REASON_COLUMNS = ["공종명", "규격", "변경사유", "요청자", "승인일"]

MATCH_KEYS = ["구분", "공종명", "규격", "단위"]

# 변경 유형
T_NEW = "신규"
T_DELETED = "삭제"
T_QTY = "수량증감"
T_PRICE = "단가변경"
T_BOTH = "복합변경"
T_SAME = "변동없음"

CHANGE_TYPES = (T_NEW, T_DELETED, T_QTY, T_PRICE, T_BOTH, T_SAME)

# 증감으로 인정하는 최소 차이 (반올림 오차 흡수)
QTY_TOLERANCE = 1e-6
PRICE_TOLERANCE = 0.5          # 원 단위
AMOUNT_TOLERANCE = 1.0         # 총액 검증 허용오차(원)

_EMPTY_TOKENS = ("", "-", "nan", "none", "null")


def _norm_text(value) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_TOKENS else text


def _key_of(row) -> tuple:
    """매칭 키. '구분'은 표준 표기로 정규화해 자재/자재비 혼용을 흡수한다."""
    gubun = config.normalize_gubun(row.get("구분")) or _norm_text(row.get("구분"))
    return (gubun, _norm_text(row.get("공종명")),
            _norm_text(row.get("규격")), _norm_text(row.get("단위")))


@dataclass
class ChangeIssue:
    level: str
    target: str
    message: str

    def as_row(self) -> dict:
        return {"수준": "오류" if self.level == "error" else "주의",
                "대상": self.target, "내용": self.message}


# ═══════════════════════════════════════════════════════════
# 1. 입력 정규화
# ═══════════════════════════════════════════════════════════
def _prepare(df: pd.DataFrame | None) -> pd.DataFrame:
    """내역서를 비교 가능한 형태로 정리하고 동일 키를 합산한다."""
    if df is None or df.empty:
        return pd.DataFrame(columns=MATCH_KEYS + ["단가", "수량", "합계"])

    work = df.copy().reset_index(drop=True)
    for col in MATCH_KEYS:
        if col not in work.columns:
            work[col] = ""

    work["구분"] = work["구분"].map(
        lambda v: config.normalize_gubun(v) or _norm_text(v))
    for col in ("공종명", "규격", "단위"):
        work[col] = work[col].map(_norm_text)

    work["단가"] = config.to_number_series(work.get("단가", 0))
    work["수량"] = config.to_number_series(work.get("수량", 0))
    work["합계"] = config.to_number_series(work.get("합계", 0))

    # 합계가 비어 있으면 단가 × 수량으로 채운다
    missing = work["합계"] == 0
    work.loc[missing, "합계"] = (work.loc[missing, "단가"] * work.loc[missing, "수량"])

    work = work[work["공종명"] != ""]
    if work.empty:
        return pd.DataFrame(columns=MATCH_KEYS + ["단가", "수량", "합계"])

    # 동일 키 중복은 수량·금액을 합산하고 단가는 가중평균으로 통합
    grouped = work.groupby(MATCH_KEYS, sort=False, dropna=False).agg(
        수량=("수량", "sum"), 합계=("합계", "sum"), 행수=("수량", "size")).reset_index()
    grouped["단가"] = grouped.apply(
        lambda r: (r["합계"] / r["수량"]) if r["수량"] else 0.0, axis=1)
    return grouped[MATCH_KEYS + ["단가", "수량", "합계", "행수"]]


def load_reasons(df_reasons: pd.DataFrame | None) -> dict:
    """변경사유 시트 → {(공종명, 규격): 사유 문자열}."""
    if df_reasons is None or df_reasons.empty:
        return {}
    out: dict = {}
    for _, row in df_reasons.iterrows():
        name = _norm_text(row.get("공종명"))
        if not name:
            continue
        spec = _norm_text(row.get("규격"))
        reason = _norm_text(row.get("변경사유"))
        requester = _norm_text(row.get("요청자"))
        if requester:
            reason = f"{reason} ({requester})" if reason else f"요청: {requester}"
        out[(name, spec)] = reason
        out.setdefault((name, ""), reason)      # 규격 미지정 조회 허용
    return out


# ═══════════════════════════════════════════════════════════
# 2. 변경 유형 판정
# ═══════════════════════════════════════════════════════════
def classify(before_qty: float, before_price: float,
             after_qty: float, after_price: float,
             *, exists_before: bool, exists_after: bool) -> str:
    """항목 1건의 변경 유형을 판정한다."""
    if not exists_before and exists_after:
        return T_NEW
    if exists_before and not exists_after:
        return T_DELETED

    qty_changed = abs(after_qty - before_qty) > QTY_TOLERANCE
    price_changed = abs(after_price - before_price) > PRICE_TOLERANCE

    if qty_changed and price_changed:
        return T_BOTH
    if qty_changed:
        return T_QTY
    if price_changed:
        return T_PRICE
    return T_SAME


# ═══════════════════════════════════════════════════════════
# 3. 대비표 생성
# ═══════════════════════════════════════════════════════════
def compare(df_before: pd.DataFrame | None, df_after: pd.DataFrame | None,
            *, df_reasons: pd.DataFrame | None = None,
            include_same: bool = True) -> tuple[pd.DataFrame, list]:
    """당초·변경 내역서를 비교해 대비표를 만든다.

    반환: (대비표 DataFrame, 경고 목록)
    """
    before = _prepare(df_before)
    after = _prepare(df_after)
    reasons = load_reasons(df_reasons)
    issues: list = []

    before_map = {_key_of(r): r for _, r in before.iterrows()}
    after_map = {_key_of(r): r for _, r in after.iterrows()}

    # 당초 순서를 유지하고, 신규 항목을 뒤에 붙인다
    keys = list(before_map.keys()) + [k for k in after_map if k not in before_map]

    rows: list = []
    for key in keys:
        b = before_map.get(key)
        a = after_map.get(key)
        exists_before, exists_after = b is not None, a is not None

        b_qty = float(b["수량"]) if exists_before else 0.0
        b_price = float(b["단가"]) if exists_before else 0.0
        b_amount = float(b["합계"]) if exists_before else 0.0
        a_qty = float(a["수량"]) if exists_after else 0.0
        a_price = float(a["단가"]) if exists_after else 0.0
        a_amount = float(a["합계"]) if exists_after else 0.0

        change_type = classify(b_qty, b_price, a_qty, a_price,
                               exists_before=exists_before, exists_after=exists_after)
        if change_type == T_SAME and not include_same:
            continue

        gubun, name, spec, unit = key
        delta = a_amount - b_amount
        rate = (delta / b_amount * 100) if abs(b_amount) > AMOUNT_TOLERANCE else None

        reason = reasons.get((name, spec)) or reasons.get((name, "")) or ""
        if change_type != T_SAME and not reason:
            issues.append(ChangeIssue("warn", name,
                                      f"{change_type} 항목에 변경 사유가 없습니다."))

        rows.append({
            "구분": gubun, "공종명": name, "규격": spec, "단위": unit,
            "당초수량": round(b_qty, 3), "당초단가": int(round(b_price)),
            "당초금액": int(round(b_amount)),
            "변경수량": round(a_qty, 3), "변경단가": int(round(a_price)),
            "변경금액": int(round(a_amount)),
            "증감수량": round(a_qty - b_qty, 3),
            "증감금액": int(round(delta)),
            "증감률(%)": round(rate, 2) if rate is not None else None,
            "변경유형": change_type,
            "변경사유": reason,
        })

    columns = ["구분", "공종명", "규격", "단위",
               "당초수량", "당초단가", "당초금액",
               "변경수량", "변경단가", "변경금액",
               "증감수량", "증감금액", "증감률(%)", "변경유형", "변경사유"]
    table = pd.DataFrame(rows, columns=columns)

    # 총액 검증
    total_before = float(before["합계"].sum()) if not before.empty else 0.0
    total_after = float(after["합계"].sum()) if not after.empty else 0.0
    total_delta = float(table["증감금액"].sum()) if not table.empty else 0.0
    expected = total_after - total_before
    if abs(total_delta - expected) > AMOUNT_TOLERANCE * max(len(table), 1):
        issues.append(ChangeIssue(
            "error", "총액 검증",
            f"증감액 합계({total_delta:,.0f})와 총액 차이({expected:,.0f})가 일치하지 않습니다."))

    log.info("대비표 생성: %d행 (당초 %d / 변경 %d)", len(table), len(before), len(after))
    return table, issues


# ═══════════════════════════════════════════════════════════
# 4. 요약
# ═══════════════════════════════════════════════════════════
def summarize_by_type(table: pd.DataFrame | None) -> pd.DataFrame:
    """변경 유형별 건수·증감액 요약."""
    columns = ["변경유형", "건수", "당초금액", "변경금액", "증감금액"]
    if table is None or table.empty:
        return pd.DataFrame(columns=columns)

    grouped = table.groupby("변경유형", sort=False).agg(
        건수=("공종명", "size"), 당초금액=("당초금액", "sum"),
        변경금액=("변경금액", "sum"), 증감금액=("증감금액", "sum")).reset_index()

    # 표기 순서를 고정한다
    order = {name: i for i, name in enumerate(CHANGE_TYPES)}
    grouped["_o"] = grouped["변경유형"].map(lambda v: order.get(v, 99))
    grouped = grouped.sort_values("_o").drop(columns=["_o"])

    total = pd.DataFrame([{
        "변경유형": "■ 합계", "건수": int(grouped["건수"].sum()),
        "당초금액": int(grouped["당초금액"].sum()),
        "변경금액": int(grouped["변경금액"].sum()),
        "증감금액": int(grouped["증감금액"].sum()),
    }])
    return pd.concat([grouped, total], ignore_index=True)[columns]


def summarize_by_cost_group(table: pd.DataFrame | None) -> pd.DataFrame:
    """비목별(자재·노무·장비) 증감 요약. 원가 영향 파악용."""
    columns = ["비목", "당초금액", "변경금액", "증감금액", "증감률(%)"]
    if table is None or table.empty:
        return pd.DataFrame(columns=columns)

    work = table.copy()
    work["비목"] = config.cost_group_series(work).fillna("미분류")
    grouped = work.groupby("비목", sort=False).agg(
        당초금액=("당초금액", "sum"), 변경금액=("변경금액", "sum"),
        증감금액=("증감금액", "sum")).reset_index()
    grouped["증감률(%)"] = grouped.apply(
        lambda r: round(r["증감금액"] / r["당초금액"] * 100, 2)
        if abs(r["당초금액"]) > AMOUNT_TOLERANCE else None, axis=1)

    total_before = int(grouped["당초금액"].sum())
    total = pd.DataFrame([{
        "비목": "■ 직접공사비 계",
        "당초금액": total_before,
        "변경금액": int(grouped["변경금액"].sum()),
        "증감금액": int(grouped["증감금액"].sum()),
        "증감률(%)": round(int(grouped["증감금액"].sum()) / total_before * 100, 2)
        if abs(total_before) > AMOUNT_TOLERANCE else None,
    }])
    return pd.concat([grouped, total], ignore_index=True)[columns]


def compare_contract_price(df_before: pd.DataFrame | None,
                           df_after: pd.DataFrame | None,
                           rates: dict, calculate_cost_summary) -> pd.DataFrame:
    """원가계산서 기준 도급액 증감 비교.

    calculate_cost_summary 는 logic_calculator 의 함수를 그대로 주입받는다.
    (모듈 간 결합을 낮추기 위한 의존성 주입)
    """
    def rows_of(df):
        if df is None or df.empty:
            df = pd.DataFrame(columns=["구분", "합계"])
        return {r["비목"].strip(): r["금액(원)"]
                for r in calculate_cost_summary(df, rates)}

    before_rows = rows_of(df_before)
    after_rows = rows_of(df_after)

    def to_int(text):
        try:
            return int(str(text).replace(",", ""))
        except (TypeError, ValueError):
            return 0

    keys = list(before_rows.keys())
    rows = []
    for key in keys:
        b = to_int(before_rows.get(key, 0))
        a = to_int(after_rows.get(key, 0))
        rows.append({
            "비목": key, "당초": b, "변경": a, "증감": a - b,
            "증감률(%)": round((a - b) / b * 100, 2) if b else None,
        })
    return pd.DataFrame(rows, columns=["비목", "당초", "변경", "증감", "증감률(%)"])


# ═══════════════════════════════════════════════════════════
# 5. 결재용 서식
# ═══════════════════════════════════════════════════════════
def build_change_report(table: pd.DataFrame | None,
                        *, group_col: str = "구분") -> pd.DataFrame:
    """엑셀 '설계변경 대비표' 시트용. 그룹 소계와 총계를 삽입한다."""
    columns = ["구분", "공종명", "규격", "단위",
               "당초수량", "당초단가", "당초금액",
               "변경수량", "변경단가", "변경금액",
               "증감금액", "변경유형", "변경사유"]
    if table is None or table.empty:
        return pd.DataFrame(columns=columns)

    work = table.copy()
    if group_col not in work.columns:
        work[group_col] = ""

    rows: list = []
    totals = {"당초금액": 0, "변경금액": 0, "증감금액": 0}

    for key in work[group_col].drop_duplicates().tolist():
        part = work[work[group_col] == key]
        for _, row in part.iterrows():
            rows.append({col: row.get(col, "") for col in columns})
        blank = {col: "" for col in columns}
        blank["공종명"] = f"▶ {key or '미분류'} 소계"
        for field in totals:
            value = int(part[field].sum())
            blank[field] = value
            totals[field] += value
        rows.append(blank)

    total_row = {col: "" for col in columns}
    total_row["공종명"] = "■ 직접공사비 합계"
    for field, value in totals.items():
        total_row[field] = value
    rows.append(total_row)

    return pd.DataFrame(rows, columns=columns)


def build_executive_summary(table: pd.DataFrame | None,
                            *, project_name: str = "",
                            contract_table: pd.DataFrame | None = None) -> pd.DataFrame:
    """임원 보고용 1p 요약. 증감 상위 항목과 총괄을 한 표로."""
    if table is None or table.empty:
        return pd.DataFrame(columns=["항목", "내용"])

    total_before = int(table["당초금액"].sum())
    total_after = int(table["변경금액"].sum())
    delta = total_after - total_before
    rate = (delta / total_before * 100) if total_before else 0

    counts = table["변경유형"].value_counts().to_dict()
    increased = table[table["증감금액"] > 0].nlargest(3, "증감금액")
    decreased = table[table["증감금액"] < 0].nsmallest(3, "증감금액")

    arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "-")
    rows = [
        {"항목": "공사명", "내용": project_name or "-"},
        {"항목": "당초 직접공사비", "내용": f"{total_before:,}원"},
        {"항목": "변경 직접공사비", "내용": f"{total_after:,}원"},
        {"항목": "증감액", "내용": f"{arrow} {abs(delta):,}원 ({rate:+.2f}%)"},
        {"항목": "변경 항목 수",
         "내용": " / ".join(f"{k} {v}건" for k, v in counts.items() if k != T_SAME) or "없음"},
    ]

    if contract_table is not None and not contract_table.empty:
        hit = contract_table[contract_table["비목"].str.contains("총 공사예정금액", na=False)]
        if not hit.empty:
            row = hit.iloc[0]
            sign = "▲" if row["증감"] > 0 else ("▼" if row["증감"] < 0 else "-")
            rows.append({"항목": "도급액 증감(제비율 반영)",
                         "내용": f"{sign} {abs(int(row['증감'])):,}원 "
                                 f"({row['당초']:,} → {row['변경']:,})"})

    for _, row in increased.iterrows():
        rows.append({"항목": "주요 증액", 
                     "내용": f"{row['공종명']} ▲{row['증감금액']:,}원"
                             + (f" — {row['변경사유']}" if row["변경사유"] else "")})
    for _, row in decreased.iterrows():
        rows.append({"항목": "주요 감액",
                     "내용": f"{row['공종명']} ▼{abs(row['증감금액']):,}원"
                             + (f" — {row['변경사유']}" if row["변경사유"] else "")})

    return pd.DataFrame(rows, columns=["항목", "내용"])


def validate(issues: list) -> pd.DataFrame:
    seen: set = set()
    rows: list = []
    for issue in issues or []:
        signature = (issue.level, issue.target, issue.message)
        if signature in seen:
            continue
        seen.add(signature)
        rows.append(issue.as_row())
    return pd.DataFrame(rows, columns=["수준", "대상", "내용"])


def sample_reason_sheet() -> pd.DataFrame:
    """변경사유 시트 작성 예시."""
    return pd.DataFrame([
        {"공종명": "소화배관 설치", "규격": "50A", "변경사유": "현장 여건상 노출배관으로 변경",
         "요청자": "시설팀", "승인일": "2026-08-05"},
        {"공종명": "바닥 방수", "규격": "우레탄 2mm", "변경사유": "누수 부위 확대 확인",
         "요청자": "안전TF", "승인일": "2026-08-07"},
    ], columns=REASON_COLUMNS)
