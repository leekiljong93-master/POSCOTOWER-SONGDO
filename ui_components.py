import streamlit as st
import pandas as pd
from datetime import date
import db_manager as db


def render_add_item_column(col, title, category_large, gubun_type, default_unit, qty_label, icon):
    with col:
        st.markdown(f"#### {icon} {title}")

        # 1. DB에서 데이터 불러오기
        df_master = db.get_all_master_items_combined()

        if not df_master.empty:
            if 'category_large' in df_master.columns and '구분' in df_master.columns:
                filtered_df = df_master[
                    (df_master['구분'] == category_large) | (df_master['category_large'] == category_large)
                    ].reset_index(drop=True)
            elif 'category_large' in df_master.columns:
                filtered_df = df_master[df_master['category_large'] == category_large].reset_index(drop=True)
            elif '구분' in df_master.columns:
                filtered_df = df_master[df_master['구분'] == category_large].reset_index(drop=True)
            else:
                filtered_df = pd.DataFrame(columns=df_master.columns)
        else:
            filtered_df = pd.DataFrame()

        if filtered_df.empty:
            st.caption(f"등록된 {title} 항목이 없습니다.")
            return

        # 1단계: 품목 선택
        unique_items = filtered_df['item_name'].dropna().astype(str).str.strip().unique().tolist()
        unique_items = [item for item in unique_items if item != "" and item.lower() != "nan"]

        if not unique_items:
            st.caption(f"등록된 {title} 품목이 없습니다.")
            return

        selected_item_name = st.selectbox(
            f"1. {title} 품목 선택",
            options=unique_items,
            key=f"item_sel_{category_large}_{title}"
        )

        # ---------------------------------------------------------
        # 불필요한 스펙 텍스트(중복 품명, 직종코드 등) 정제 함수
        # ---------------------------------------------------------
        def get_cleaned_spec(raw_spec, current_item_name):
            if not raw_spec or str(raw_spec).lower() == 'nan' or str(raw_spec) == '-':
                return ""

            parts = [p.strip() for p in str(raw_spec).split(',')]
            clean_parts = []

            for p in parts:
                if p == current_item_name:
                    continue
                if "직종코드" in p:
                    continue
                if not p:
                    continue
                clean_parts.append(p)

            return ", ".join(clean_parts)

        # 2단계: 규격 선택
        spec_df = filtered_df[filtered_df['item_name'] == selected_item_name].reset_index(drop=True)

        def format_spec_only(idx):
            row = spec_df.loc[idx]
            raw_spec = row.get('spec', '')
            unit = str(row.get('unit', default_unit)).strip()

            cleaned_spec = get_cleaned_spec(raw_spec, selected_item_name)
            display_spec = cleaned_spec if cleaned_spec else "단일 규격"

            return f"{display_spec} ({unit})"

        selected_spec_idx = st.selectbox(
            f"2. 규격 선택",
            options=range(len(spec_df)),
            format_func=format_spec_only,
            key=f"spec_sel_{category_large}_{title}"
        )

        selected_row = spec_df.iloc[selected_spec_idx]

        # ---------------------------------------------------------
        # 3단계: 단가 연동 및 수기 수정 (규격/품목 전환 시 실시간 연동)
        # ---------------------------------------------------------
        default_price = int(float(selected_row.get('unit_price', 0)))

        user_price = st.number_input(
            f"3. 단가 (수정 가능)",
            value=default_price,
            step=1000,
            format="%d",
            key=f"price_disp_{category_large}_{title}_{selected_item_name}_{selected_spec_idx}"
        )

        # 4단계: 수량 입력
        if qty_label:
            qty = st.number_input(
                f"4. {qty_label} 입력",
                min_value=0.0,
                value=1.0,
                step=1.0,
                key=f"qty_{category_large}_{title}"
            )
        else:
            qty = 1.0

        unit = selected_row.get('unit', default_unit)

        # 5단계: 추가 버튼
        st.markdown("<div style='margin-top: 6px;'></div>", unsafe_allow_html=True)
        if st.button(f"➕ 내역서에 추가", key=f"btn_{category_large}_{title}", use_container_width=True):

            final_item_name = selected_row.get('item_name', '')
            raw_spec = selected_row.get('spec', '')

            cleaned_spec_val = get_cleaned_spec(raw_spec, final_item_name)

            # 💡 [핵심 변경 사항] 공종명에 스펙을 괄호로 붙이지 않고, '규격' 열을 따로 분리합니다.
            new_row = {
                "구분": gubun_type,
                "공종명": final_item_name,  # 이름만 깔끔하게 저장
                "규격": cleaned_spec_val if cleaned_spec_val else "",  # 규격만 따로 저장
                "단위": unit,
                "단가": user_price,
                "수량": qty,
                "합계": int(user_price * qty),
                "시작일": pd.Timestamp.now().strftime("%Y-%m-%d"),
                "종료일": pd.Timestamp.now().strftime("%Y-%m-%d")
            }

            # 기존 DataFrame에 새로운 행 추가
            st.session_state.estimate_data = pd.concat(
                [st.session_state.estimate_data, pd.DataFrame([new_row])],
                ignore_index=True
            )

            # 🌟 [핵심 수정] 컬럼 순서를 '규격'이 포함되도록 재정렬합니다.
            desired_order = ["구분", "공종명", "규격", "단위", "단가", "수량", "합계", "시작일", "종료일"]
            existing_cols = [c for c in desired_order if c in st.session_state.estimate_data.columns] + \
                            [c for c in st.session_state.estimate_data.columns if c not in desired_order]
            st.session_state.estimate_data = st.session_state.estimate_data[existing_cols]

            st.rerun()


# -------------------------------------------------------------
# 다이얼로그 (팝업창) 로직
# -------------------------------------------------------------
@st.dialog("⚠️ 현재 프로젝트 삭제 확인")
def delete_confirmation(project_name):
    st.warning(
        f"**'{project_name}'** 프로젝트를 현재 브라우저 작업 목록에서 삭제하시겠습니까?\n\n"
        "☁️ Google Sheets에 저장된 프로젝트는 삭제되지 않으며, 클라우드 보관소에서 다시 불러올 수 있습니다."
    )
    c1, c2 = st.columns(2)
    if c1.button("🗑️ 현재 목록에서 삭제", use_container_width=True):
        if project_name in st.session_state.projects:
            del st.session_state.projects[project_name]

        # 빈 프로젝트 생성 시에도 '규격' 컬럼 포함 보장
        desired_order = ["구분", "공종명", "규격", "단위", "단가", "수량", "합계", "시작일", "종료일"]
        if st.session_state.projects:
            st.session_state.current_project = list(st.session_state.projects.keys())[0]
        else:
            st.session_state.projects = {
                "기본 프로젝트": pd.DataFrame(columns=desired_order)}
            st.session_state.current_project = "기본 프로젝트"

        df_loaded = st.session_state.projects[st.session_state.current_project].copy()
        existing_cols = [c for c in desired_order if c in df_loaded.columns] + \
                        [c for c in df_loaded.columns if c not in desired_order]
        st.session_state.estimate_data = df_loaded[existing_cols]
        st.rerun()
    if c2.button("취소", use_container_width=True):
        st.rerun()


@st.dialog("⚠️ 클라우드 프로젝트 삭제 확인")
def delete_cloud_confirmation(project_name):
    st.warning(f"정말로 클라우드(구글 시트) 보관소에서 '{project_name}'을 삭제하시겠습니까?")
    c1, c2 = st.columns(2)
    if c1.button("완전히 삭제", use_container_width=True):
        with st.spinner("삭제 중..."):
            res = db.delete_project_from_cloud(project_name)
            if res is True:
                st.session_state.cloud_project_list = db.get_cloud_projects_list()
                st.success("삭제되었습니다!")
                st.rerun()
            else:
                st.error(f"삭제 실패: {res}")
    if c2.button("취소", use_container_width=True):
        st.rerun()