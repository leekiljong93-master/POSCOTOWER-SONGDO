# -*- coding: utf-8 -*-
"""
ui_components.py
─────────────────────────────────────────────────────────────
품목 추가 위젯 및 확인 팝업(dialog)

[패치 ④] '자재비'/'자재' 하드코딩 제거 → config 매핑만 사용
[패치 ⑤] st.session_state.estimate_data 직접 조작 제거 → state_manager 경유
[패치 ③] db 반환값을 Result 로 일원화하여 처리
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import config
import db_manager as db
import state_manager as state

log = config.get_logger("ui")

# 시트별 위젯 표시 옵션 (아이콘 / 기본단위 / 수량 라벨)
SHEET_UI_PRESET = {
    "자재비": {"icon": "🧱", "default_unit": "식", "qty_label": "수량"},
    "인건비": {"icon": "👷", "default_unit": "인", "qty_label": "인원"},
    "장비비": {"icon": "🏗️", "default_unit": "시간", "qty_label": "시간"},
    "세트": {"icon": "📦", "default_unit": "식", "qty_label": "수량"},
}


# ═══════════════════════════════════════════════════════════
# 규격 텍스트 정제
# ═══════════════════════════════════════════════════════════
def clean_spec(raw_spec, item_name: str) -> str:
    """규격 문자열에서 품명 중복·직종코드 등 불필요 토큰을 제거한다."""
    if raw_spec is None:
        return ""
    text = str(raw_spec).strip()
    if not text or text.lower() in ("nan", "none", "-"):
        return ""

    keep = []
    for part in (p.strip() for p in text.split(",")):
        if not part or part == item_name or "직종코드" in part:
            continue
        keep.append(part)
    return ", ".join(keep)


# ═══════════════════════════════════════════════════════════
# 품목 추가 위젯
# ═══════════════════════════════════════════════════════════
def render_add_item_column(col, sheet_name: str, *, gubun: str | None = None,
                           icon: str | None = None, default_unit: str | None = None,
                           qty_label: str | None = None, editable: bool = True):
    """마스터 시트 1개에 대한 '품목 선택 → 규격 → 단가 → 수량 → 추가' 위젯.

    sheet_name 만 넘기면 나머지는 config / SHEET_UI_PRESET 에서 자동 결정된다.
    """
    canonical_sheet = config.normalize_sheet_name(sheet_name) or sheet_name
    target_gubun = gubun or config.SHEET_TO_GUBUN.get(canonical_sheet, canonical_sheet)
    preset = SHEET_UI_PRESET.get(canonical_sheet, {})
    icon = icon or preset.get("icon", "•")
    default_unit = default_unit or preset.get("default_unit", "식")
    qty_label = qty_label if qty_label is not None else preset.get("qty_label", "수량")

    key_ns = f"add_{canonical_sheet}"

    with col:
        st.markdown(f"#### {icon} {canonical_sheet}")

        if not editable:
            st.caption("편집 권한이 필요합니다.")
            return

        df_master = db.get_filtered_master_items(canonical_sheet)
        if df_master.empty:
            st.caption(f"등록된 {canonical_sheet} 항목이 없습니다.")
            return

        items = (df_master["item_name"].dropna().astype(str).str.strip()
                 .replace("", pd.NA).dropna().unique().tolist())
        items = [i for i in items if i.lower() != "nan"]
        if not items:
            st.caption(f"등록된 {canonical_sheet} 품목이 없습니다.")
            return

        selected_item = st.selectbox(f"1. {canonical_sheet} 품목 선택", options=items,
                                     key=f"{key_ns}_item")

        spec_df = df_master[df_master["item_name"] == selected_item].reset_index(drop=True)

        def _format_spec(idx: int) -> str:
            row = spec_df.loc[idx]
            unit = str(row.get("unit", default_unit)).strip() or default_unit
            spec = clean_spec(row.get("spec", ""), selected_item) or "단일 규격"
            return f"{spec} ({unit})"

        spec_idx = st.selectbox("2. 규격 선택", options=range(len(spec_df)),
                                format_func=_format_spec, key=f"{key_ns}_spec")
        selected_row = spec_df.iloc[spec_idx]

        try:
            default_price = int(float(selected_row.get("unit_price", 0) or 0))
        except (TypeError, ValueError):
            log.warning("단가 파싱 실패: %s / %s", selected_item, selected_row.get("unit_price"))
            default_price = 0

        # 품목·규격이 바뀌면 단가 위젯이 새로 생성되도록 key에 포함
        user_price = st.number_input(
            "3. 단가 (수정 가능)", value=default_price, step=1000, format="%d",
            key=f"{key_ns}_price_{selected_item}_{spec_idx}",
        )

        if qty_label:
            qty = st.number_input(f"4. {qty_label} 입력", min_value=0.0, value=1.0, step=1.0,
                                  key=f"{key_ns}_qty")
        else:
            qty = 1.0

        unit = str(selected_row.get("unit", default_unit)).strip() or default_unit

        st.markdown("<div style='margin-top: 6px;'></div>", unsafe_allow_html=True)
        if st.button("➕ 내역서에 추가", key=f"{key_ns}_btn", use_container_width=True):
            if qty <= 0:
                st.warning("수량이 0입니다. 값을 확인하세요.")
                return

            new_row = {
                "구분": target_gubun,
                "공종명": str(selected_row.get("item_name", "")),
                "규격": clean_spec(selected_row.get("spec", ""), selected_item),
                "단위": unit,
                "단가": user_price,
                "수량": qty,
                "합계": int(round(user_price * qty)),
                "시작일": pd.Timestamp.now().normalize(),
                "종료일": pd.Timestamp.now().normalize(),
            }

            # [패치 ⑤] SSOT 경유 단일 기록
            current = state.get_estimate()
            state.set_estimate(pd.concat([current, pd.DataFrame([new_row])], ignore_index=True))
            log.info("항목 추가: %s / %s", target_gubun, new_row["공종명"])
            st.rerun()


# ═══════════════════════════════════════════════════════════
# 확인 팝업
# ═══════════════════════════════════════════════════════════
@st.dialog("⚠️ 현재 프로젝트 삭제 확인")
def delete_confirmation(project_name: str):
    st.warning(
        f"**'{project_name}'** 프로젝트를 현재 브라우저 작업 목록에서 삭제하시겠습니까?\n\n"
        "☁️ Google Sheets에 저장된 프로젝트는 삭제되지 않으며, 클라우드 보관소에서 다시 불러올 수 있습니다."
    )
    c1, c2 = st.columns(2)
    if c1.button("🗑️ 현재 목록에서 삭제", use_container_width=True):
        ok, msg = state.delete_project(project_name)
        (st.toast if ok else st.error)(msg)
        st.rerun()
    if c2.button("취소", use_container_width=True):
        st.rerun()


@st.dialog("⚠️ 전체 항목 삭제 확인")
def delete_all_confirmation():
    st.error("현재 프로젝트의 모든 내역을 정말로 삭제하시겠습니까?\n\n"
             "이 작업은 되돌릴 수 없습니다. (클라우드 저장본은 영향받지 않습니다)")
    c1, c2 = st.columns(2)
    if c1.button("🔥 완전히 비우기", type="primary", use_container_width=True):
        state.clear_current()
        st.rerun()
    if c2.button("취소", use_container_width=True):
        st.rerun()


@st.dialog("⚠️ 클라우드 프로젝트 삭제 확인")
def delete_cloud_confirmation(project_name: str):
    st.warning(f"정말로 클라우드(구글 시트) 보관소에서 **'{project_name}'** 을 삭제하시겠습니까?\n\n"
               "저장된 내역이 영구 삭제됩니다.")
    c1, c2 = st.columns(2)
    if c1.button("완전히 삭제", type="primary", use_container_width=True):
        with st.spinner("삭제 중..."):
            res = db.delete_project_from_cloud(project_name)
        if res:  # [패치 ③] Result.__bool__
            db.get_cloud_projects_list.clear()
            st.session_state.cloud_project_list = db.get_cloud_projects_list()
            st.success(res.message)
            st.rerun()
        else:
            st.error(res.message)
    if c2.button("취소", use_container_width=True):
        st.rerun()


@st.dialog("⚠️ 저장 충돌 발생")
def overwrite_conflict_dialog(project_name: str, stored_date: str):
    """[패치 ①] 낙관적 동시성 검사에서 충돌이 감지된 경우의 선택지 제공."""
    st.error(
        f"다른 사용자가 **{stored_date}** 에 '{project_name}'을 저장했습니다.\n\n"
        "덮어쓰면 그 사용자의 작업이 사라집니다."
    )
    c1, c2 = st.columns(2)
    if c1.button("⚠️ 그래도 덮어쓰기", type="primary", use_container_width=True):
        with st.spinner("덮어쓰는 중..."):
            res = db.save_project_to_cloud(project_name, state.get_estimate(),
                                           expected_version=None)
        if res:
            state.set_version(project_name, res.data)
            st.success("덮어쓰기 저장 완료")
        else:
            st.error(res.message)
        st.rerun()
    if c2.button("취소 (최신본 확인)", use_container_width=True):
        st.rerun()
