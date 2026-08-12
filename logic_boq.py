# -*- coding: utf-8 -*-
"""
logic_boq.py
─────────────────────────────────────────────────────────────
일위대가(세트) 전개 엔진 — 고도화 ①

배경
  기존 구조에서 '세트'는 구성 내역 없이 뭉친 단가 하나로만 존재했고,
  내역서에는 전액 '자재'로 기록되었다. 조달청 원가계산은 간접노무비·산재·고용·
  건강·연금·퇴직공제·기타경비를 모두 '직접노무비'에서 산출하므로, 세트 안의
  노무비가 자재비로 흡수되면 이 항목들이 연쇄적으로 과소계상된다.
  (실측: 세트 3,000만원 1건 → 총 도급액 약 760만원 과소)

이 모듈이 하는 일
  1. '세트구성' 시트로 세트를 구성품(자재·노무·장비)으로 정의
  2. 구성품 단가 × 소요량 × (1+할증률)  →  세트 단가 자동 산출
  3. 중첩 세트(세트 안의 세트) 재귀 해석 + 순환 참조 탐지
  4. 내역서의 세트 행을 구성품 행으로 전개 → 비목이 정확해짐
  5. 일위대가표(호표) 생성 → 엑셀 시트로 출력
  6. 공종 계층별 소계·누계 삽입 (을지 실무 서식)
  7. 누락 품목·단가 0원·순환 참조 검증 리포트

의존: config (normalize_gubun / to_number_series / get_logger)
      ※ pandas 외 외부 패키지 불필요. Streamlit 없이 단위 검증 가능.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

import config

log = config.get_logger("boq")

# ═══════════════════════════════════════════════════════════
# 0. 스키마 및 상수
# ═══════════════════════════════════════════════════════════
SET_SHEET = "세트구성"
SET_COLUMNS = ["set_name", "seq", "구분", "item_name", "spec", "unit", "소요량", "할증률", "비고"]

MAX_DEPTH = 5                  # 중첩 세트 허용 깊이
ROUND_UNIT = 1                 # 단가 반올림 단위(원). 10 → 10원 단위
ROUND_MODE = "round"           # "round"(사사오입) | "floor"(절사)

# 전개 결과 행에 붙는 추적용 컬럼
TRACE_COLUMNS = ["상위세트", "전개깊이", "산출근거"]

_EMPTY_TOKENS = ("", "-", "nan", "none", "null")


def _norm_text(value) -> str:
    """공백·대소문자·빈값 토큰을 정규화한 비교용 문자열."""
    if value is None:
        return ""
    text = str(value).strip()
    return "" if text.lower() in _EMPTY_TOKENS else text


def _num(value, default: float = 0.0) -> float:
    """단일 값 숫자 변환. '1,200' 같은 콤마 표기도 처리."""
    series = config.to_number_series([value], default=default)
    return float(series.iloc[0]) if len(series) else default


def _round_price(value: float) -> int:
    """단가 반올림. 기관별로 절사/사사오입 기준이 다르므로 상수로 노출."""
    if ROUND_UNIT <= 1:
        return int(value) if ROUND_MODE == "floor" else int(round(value))
    scaled = value / ROUND_UNIT
    scaled = int(scaled) if ROUND_MODE == "floor" else round(scaled)
    return int(scaled * ROUND_UNIT)


# ═══════════════════════════════════════════════════════════
# 1. 결과 컨테이너
# ═══════════════════════════════════════════════════════════
@dataclass
class Issue:
    """검증 경고 1건."""
    level: str        # "error" | "warn"
    set_name: str
    item: str
    message: str

    def as_row(self) -> dict:
        return {"수준": "오류" if self.level == "error" else "주의",
                "세트명": self.set_name, "대상": self.item, "내용": self.message}


@dataclass
class SetResolution:
    """세트 1건의 해석 결과."""
    set_name: str
    unit: str = "식"
    unit_price: int = 0
    components: list = field(default_factory=list)   # 전개된 말단 구성품
    issues: list = field(default_factory=list)
    resolved: bool = True

    def cost_breakdown(self) -> dict:
        """세트 단가를 비목별로 분해 (자재/노무/장비)."""
        out = {group: 0 for group in config.COST_GROUPS}
        for comp in self.components:
            group = comp.get("비목")
            if group in out:
                out[group] += comp["금액"]
        return out


# ═══════════════════════════════════════════════════════════
# 2. 입력 정규화
# ═══════════════════════════════════════════════════════════
def empty_set_sheet() -> pd.DataFrame:
    return pd.DataFrame(columns=SET_COLUMNS)


def normalize_set_sheet(df: pd.DataFrame | None) -> pd.DataFrame:
    """세트구성 시트를 표준 스키마로 정렬한다."""
    if df is None or df.empty:
        return empty_set_sheet()

    out = df.copy().reset_index(drop=True)
    for col in SET_COLUMNS:
        if col not in out.columns:
            out[col] = "" if col not in ("소요량", "할증률", "seq") else 0

    out["set_name"] = out["set_name"].map(_norm_text)
    out["item_name"] = out["item_name"].map(_norm_text)
    out["spec"] = out["spec"].map(_norm_text)
    out["unit"] = out["unit"].map(_norm_text)
    out["비고"] = out["비고"].map(_norm_text)
    out["구분"] = out["구분"].map(lambda v: config.normalize_gubun(v) or _norm_text(v))
    out["소요량"] = config.to_number_series(out["소요량"])
    out["할증률"] = config.to_number_series(out["할증률"])
    out["seq"] = config.to_number_series(out["seq"])

    out = out[out["set_name"] != ""]
    return out[SET_COLUMNS].reset_index(drop=True)


def build_set_index(df_sets: pd.DataFrame | None) -> dict[str, pd.DataFrame]:
    """세트명 → 구성 DataFrame 사전."""
    normalized = normalize_set_sheet(df_sets)
    if normalized.empty:
        return {}
    index = {}
    for name, part in normalized.groupby("set_name", sort=False):
        index[name] = part.sort_values("seq", kind="stable").reset_index(drop=True)
    return index


def build_price_index(df_master: pd.DataFrame | None) -> dict:
    """마스터 단가 조회 색인.

    반환 구조
      {(표준구분, 품명, 규격): {"unit_price": x, "unit": y}, ...}
      + 규격 미지정 조회를 위한 (표준구분, 품명) → 후보 리스트
    """
    exact: dict = {}
    loose: dict = {}
    if df_master is None or df_master.empty:
        return {"exact": exact, "loose": loose}

    df = df_master.copy()
    price = config.to_number_series(df.get("unit_price", 0))

    for i, row in df.reset_index(drop=True).iterrows():
        gubun = config.normalize_gubun(row.get("구분"))
        item = _norm_text(row.get("item_name"))
        if not gubun or not item:
            continue
        spec = _norm_text(row.get("spec"))
        record = {"unit_price": float(price.iloc[i]),
                  "unit": _norm_text(row.get("unit")) or "식",
                  "spec": spec}
        exact.setdefault((gubun, item, spec), record)
        loose.setdefault((gubun, item), []).append(record)

    return {"exact": exact, "loose": loose}


def _lookup_price(price_index: dict, gubun: str, item: str, spec: str):
    """규격 일치 → 규격 공백 → 단일 후보 순으로 단가를 찾는다."""
    exact, loose = price_index["exact"], price_index["loose"]
    key = (gubun, item, _norm_text(spec))
    if key in exact:
        return exact[key], None

    blank = (gubun, item, "")
    if blank in exact:
        return exact[blank], f"규격 '{spec}' 미등록 → 규격 공백 단가 적용"

    candidates = loose.get((gubun, item), [])
    if len(candidates) == 1:
        return candidates[0], f"규격 '{spec}' 불일치 → 유일 후보({candidates[0]['spec'] or '공백'}) 적용"
    if len(candidates) > 1:
        return None, f"규격 '{spec}' 불일치, 후보 {len(candidates)}건 → 자동 선택 불가"
    return None, None


# ═══════════════════════════════════════════════════════════
# 3. 세트 해석 (재귀)
# ═══════════════════════════════════════════════════════════
def resolve_set(set_name: str, set_index: dict, price_index: dict,
                *, _path: tuple = (), _memo: dict | None = None) -> SetResolution:
    """세트 1건을 말단 구성품까지 전개하고 단가를 산출한다.

    · 중첩 세트는 재귀 해석하되 MAX_DEPTH 를 넘으면 중단
    · 순환 참조(A→B→A)는 즉시 오류 처리하여 무한 루프를 막는다
    """
    memo = _memo if _memo is not None else {}
    name = _norm_text(set_name)

    if name in memo:
        return memo[name]

    if name in _path:
        cycle = " → ".join(list(_path) + [name])
        res = SetResolution(name, resolved=False,
                            issues=[Issue("error", name, name, f"순환 참조: {cycle}")])
        log.error("순환 참조 탐지: %s", cycle)
        return res

    if len(_path) >= MAX_DEPTH:
        return SetResolution(name, resolved=False, issues=[
            Issue("error", name, name, f"중첩 깊이 {MAX_DEPTH} 초과로 전개 중단")])

    if name not in set_index:
        return SetResolution(name, resolved=False, issues=[
            Issue("error", name, name, f"'{SET_SHEET}' 시트에 구성 내역이 없습니다")])

    rows = set_index[name]
    components: list = []
    issues: list = []
    total = 0.0

    for _, row in rows.iterrows():
        gubun = _norm_text(row["구분"])
        item = row["item_name"]
        spec = row["spec"]
        qty = float(row["소요량"])
        markup = float(row["할증률"])
        effective_qty = qty * (1.0 + markup / 100.0)

        if not item:
            issues.append(Issue("warn", name, "(품명 없음)", "품명이 비어 있어 건너뜀"))
            continue
        if qty <= 0:
            issues.append(Issue("warn", name, item, f"소요량이 {qty} 이므로 금액 0원"))

        # ── 중첩 세트 ──
        if gubun == "세트":
            child = resolve_set(item, set_index, price_index,
                                _path=_path + (name,), _memo=memo)
            issues.extend(child.issues)
            if not child.resolved:
                issues.append(Issue("error", name, item, "하위 세트 해석 실패"))
                continue
            for comp in child.components:
                scaled = dict(comp)
                scaled["소요량"] = comp["소요량"] * effective_qty
                scaled["금액"] = comp["단가"] * scaled["소요량"]
                scaled["상위세트"] = name
                scaled["전개깊이"] = comp["전개깊이"] + 1
                scaled["산출근거"] = f"{item} × {effective_qty:g}"
                components.append(scaled)
                total += scaled["금액"]
            continue

        # ── 말단 품목 ──
        cost_group = config.cost_group_of(gubun)
        if cost_group not in config.COST_GROUPS:
            issues.append(Issue("error", name, item, f"구분 '{gubun}' 을 인식할 수 없음"))
            continue

        sheet_gubun = config.normalize_gubun(gubun)
        record, note = _lookup_price(price_index, sheet_gubun, item, spec)
        if note:
            issues.append(Issue("warn", name, item, note))
        if record is None:
            issues.append(Issue("error", name, item,
                                f"마스터({config.GUBUN_TO_SHEET.get(sheet_gubun, sheet_gubun)})에 단가 없음"))
            continue

        unit_price = record["unit_price"]
        if unit_price <= 0:
            issues.append(Issue("warn", name, item, "단가가 0원으로 등록되어 있음"))

        amount = unit_price * effective_qty
        components.append({
            "비목": cost_group,
            "구분": sheet_gubun,
            "공종명": item,
            "규격": spec or record.get("spec", ""),
            "단위": _norm_text(row["unit"]) or record["unit"],
            "단가": unit_price,
            "소요량": effective_qty,
            "금액": amount,
            "상위세트": name,
            "전개깊이": 1,
            "산출근거": (f"소요량 {qty:g}" + (f" × 할증 {markup:g}%" if markup else "")),
        })
        total += amount

    resolution = SetResolution(
        set_name=name,
        unit=_norm_text(rows.iloc[0].get("unit")) or "식",
        unit_price=_round_price(total),
        components=components,
        issues=issues,
        resolved=not any(i.level == "error" for i in issues),
    )
    memo[name] = resolution
    return resolution


def resolve_all_sets(set_index: dict, price_index: dict) -> dict[str, SetResolution]:
    """등록된 모든 세트를 해석한다."""
    memo: dict = {}
    return {name: resolve_set(name, set_index, price_index, _memo=memo)
            for name in set_index}


# ═══════════════════════════════════════════════════════════
# 4. 내역서 전개
# ═══════════════════════════════════════════════════════════
def expand_estimate(df_estimate: pd.DataFrame | None, set_index: dict,
                    price_index: dict, *, mode: str = "explode") -> tuple[pd.DataFrame, list]:
    """내역서의 세트 행을 처리한다.

    mode="explode" : 세트를 구성품 행으로 펼친다 (원가계산 정확 — 권장)
    mode="price"   : 세트를 1행으로 유지하되 단가만 자동 산출값으로 갱신
    """
    if df_estimate is None or df_estimate.empty:
        return (pd.DataFrame(columns=config.ESTIMATE_COLUMNS + TRACE_COLUMNS), [])

    df = df_estimate.copy().reset_index(drop=True)
    df["단가"] = config.to_number_series(df.get("단가", 0))
    df["수량"] = config.to_number_series(df.get("수량", 0))

    out_rows: list = []
    issues: list = []
    memo: dict = {}

    for _, row in df.iterrows():
        gubun = config.normalize_gubun(row.get("구분"))
        base = {col: row.get(col, "") for col in config.ESTIMATE_COLUMNS if col in df.columns}

        if gubun != "세트":
            base["상위세트"] = ""
            base["전개깊이"] = 0
            base["산출근거"] = ""
            base["합계"] = int(round(_num(row.get("단가")) * _num(row.get("수량"))))
            out_rows.append(base)
            continue

        set_name = _norm_text(row.get("공종명"))
        qty = float(row.get("수량") or 0)
        res = resolve_set(set_name, set_index, price_index, _memo=memo)
        issues.extend(res.issues)

        if not res.resolved:
            # 해석 실패 시 원본 행을 보존하되 경고를 남긴다 (데이터 소실 방지)
            base["상위세트"] = ""
            base["전개깊이"] = 0
            base["산출근거"] = "⚠️ 세트 해석 실패 — 구성 내역 확인 필요"
            base["합계"] = int(round(_num(row.get("단가")) * qty))
            out_rows.append(base)
            continue

        if mode == "price":
            base["구분"] = "세트"
            base["단가"] = res.unit_price
            base["단위"] = base.get("단위") or res.unit
            base["합계"] = int(round(res.unit_price * qty))
            base["상위세트"] = ""
            base["전개깊이"] = 0
            base["산출근거"] = f"일위대가 자동산출 (구성 {len(res.components)}종)"
            out_rows.append(base)
            continue

        # explode
        for comp in res.components:
            total_qty = comp["소요량"] * qty
            out_rows.append({
                "구분": comp["구분"],
                "공종명": comp["공종명"],
                "규격": comp["규격"],
                "단위": comp["단위"],
                "단가": comp["단가"],
                "수량": total_qty,
                "합계": int(round(comp["단가"] * total_qty)),
                "시작일": row.get("시작일", ""),
                "종료일": row.get("종료일", ""),
                "상위세트": set_name,
                "전개깊이": comp["전개깊이"],
                "산출근거": f"{set_name} {qty:g}{res.unit} × {comp['산출근거']}",
            })

    columns = [c for c in config.ESTIMATE_COLUMNS if c in df.columns] + TRACE_COLUMNS
    result = pd.DataFrame(out_rows)
    for col in columns:
        if col not in result.columns:
            result[col] = ""
    return result[columns], issues


# ═══════════════════════════════════════════════════════════
# 5. 일위대가표(호표) 생성
# ═══════════════════════════════════════════════════════════
def build_ilwidaega_table(resolutions: dict[str, SetResolution],
                          *, only: list | None = None) -> pd.DataFrame:
    """엑셀 '일위대가표' 시트용 DataFrame.

    세트별로 구성품을 나열하고 마지막에 '계' 행을 붙인다.
    (엑셀 서식기의 ▶ / ■ 접두어 규칙과 호환되도록 소계 표기를 맞춤)
    """
    names = only if only else list(resolutions.keys())
    rows: list = []

    for no, name in enumerate(names, start=1):
        res = resolutions.get(name)
        if res is None:
            continue
        rows.append({"호표": f"제{no}호표", "비목": "", "품명": name,
                     "규격": "", "단위": res.unit, "수량": "",
                     "단가": "", "금액": "", "비고": "일위대가"})
        for comp in res.components:
            rows.append({
                "호표": "", "비목": comp["비목"], "품명": comp["공종명"],
                "규격": comp["규격"], "단위": comp["단위"],
                "수량": round(comp["소요량"], 4),
                "단가": int(comp["단가"]),
                "금액": int(round(comp["금액"])),
                "비고": comp["산출근거"],
            })
        breakdown = res.cost_breakdown()
        rows.append({
            "호표": "", "비목": "", "품명": f"▶ {name} 계", "규격": "",
            "단위": res.unit, "수량": 1, "단가": res.unit_price,
            "금액": res.unit_price,
            "비고": " / ".join(f"{k} {v:,.0f}" for k, v in breakdown.items() if v),
        })

    return pd.DataFrame(rows, columns=["호표", "비목", "품명", "규격", "단위",
                                       "수량", "단가", "금액", "비고"])


# ═══════════════════════════════════════════════════════════
# 6. 공종 계층 소계 (을지 서식)
# ═══════════════════════════════════════════════════════════
def insert_subtotals(df: pd.DataFrame | None, *, group_col: str = "상위세트",
                     label_fallback: str = "기타") -> pd.DataFrame:
    """그룹별 소계 행과 총계 행을 삽입한 내역서를 만든다.

    group_col 예시
      · "상위세트" → 세트 단위로 묶음 (전개 결과에 자연스러움)
      · "구분"     → 자재/노무/장비 비목별 묶음
      · "대공종"   → 사용자가 별도 컬럼을 운용하는 경우
    """
    if df is None or df.empty:
        return pd.DataFrame(columns=list(df.columns) if df is not None else [])

    work = df.copy().reset_index(drop=True)
    work["합계"] = config.to_number_series(work.get("합계", 0))
    if group_col not in work.columns:
        work[group_col] = label_fallback

    keys = work[group_col].map(lambda v: _norm_text(v) or label_fallback)
    rows: list = []
    grand = 0.0

    for key in keys.drop_duplicates().tolist():
        part = work[keys == key]
        rows.extend(part.to_dict("records"))
        subtotal = float(part["합계"].sum())
        grand += subtotal
        blank = {col: "" for col in work.columns}
        blank.update({"공종명": f"▶ {key} 소계", "합계": int(round(subtotal))})
        rows.append(blank)

    total_row = {col: "" for col in work.columns}
    total_row.update({"공종명": "■ 직접공사비 합계", "합계": int(round(grand))})
    rows.append(total_row)

    return pd.DataFrame(rows, columns=work.columns)


# ═══════════════════════════════════════════════════════════
# 7. 검증 리포트
# ═══════════════════════════════════════════════════════════
def validate(resolutions: dict[str, SetResolution],
             extra_issues: list | None = None) -> pd.DataFrame:
    """세트 전체의 검증 결과를 표로 반환한다. 화면 경고 표시용."""
    collected: list = []
    seen: set = set()

    def push(issue: Issue):
        signature = (issue.level, issue.set_name, issue.item, issue.message)
        if signature not in seen:
            seen.add(signature)
            collected.append(issue.as_row())

    for res in resolutions.values():
        for issue in res.issues:
            push(issue)
    for issue in (extra_issues or []):
        push(issue)

    return pd.DataFrame(collected, columns=["수준", "세트명", "대상", "내용"])


def summarize(resolutions: dict[str, SetResolution]) -> pd.DataFrame:
    """세트 목록 요약 — 단가와 비목 구성을 한눈에 확인."""
    rows = []
    for name, res in resolutions.items():
        breakdown = res.cost_breakdown()
        rows.append({
            "세트명": name,
            "단위": res.unit,
            "산출단가": res.unit_price,
            "구성품수": len(res.components),
            **{f"{g}비": int(round(breakdown.get(g, 0))) for g in config.COST_GROUPS},
            "상태": "정상" if res.resolved else "확인필요",
        })
    columns = ["세트명", "단위", "산출단가", "구성품수"] + \
              [f"{g}비" for g in config.COST_GROUPS] + ["상태"]
    return pd.DataFrame(rows, columns=columns)


def sample_set_sheet() -> pd.DataFrame:
    """세트구성 시트 작성 예시 (양식 다운로드용)."""
    return pd.DataFrame([
        {"set_name": "소화배관 설치(50A)", "seq": 1, "구분": "자재",
         "item_name": "백강관", "spec": "50A", "unit": "m", "소요량": 1.0,
         "할증률": 5.0, "비고": "손실 할증 5%"},
        {"set_name": "소화배관 설치(50A)", "seq": 2, "구분": "자재",
         "item_name": "엘보", "spec": "50A", "unit": "EA", "소요량": 0.3,
         "할증률": 0, "비고": ""},
        {"set_name": "소화배관 설치(50A)", "seq": 3, "구분": "노무",
         "item_name": "배관공", "spec": "", "unit": "인", "소요량": 0.12,
         "할증률": 0, "비고": "품셈 기준"},
        {"set_name": "소화배관 설치(50A)", "seq": 4, "구분": "노무",
         "item_name": "보통인부", "spec": "", "unit": "인", "소요량": 0.05,
         "할증률": 0, "비고": ""},
        {"set_name": "소화배관 설치(50A)", "seq": 5, "구분": "장비",
         "item_name": "용접기", "spec": "", "unit": "시간", "소요량": 0.2,
         "할증률": 0, "비고": ""},
    ], columns=SET_COLUMNS)
