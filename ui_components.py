import streamlit as st
import pandas as pd
from datetime import date
import db_manager as db

def render_add_item_column(col_obj, title, sheet_name, category, default_unit, unit_label, icon):
    """자재비, 인건비, 장비비, 세트 항목 추가 UI 컴포넌트"""
    with col_obj:
        st.markdown(f"##### {icon} {title}")
        df_items = db.get_filtered_master_items(sheet_name=sheet_name)
        item_names = df_items['item_name'].tolist() if not df_items.empty else ["데이터 없음"]
        
        selected_item = st.selectbox("항목 선택", item_names, key=f"{sheet_name}_sel")
        
        if sheet_name == "세트":
            st.write("\n\n")
            qty = 1.0
        else:
            qty = st.number_input(unit_label, min_value=0.0, step=1.0, format="%.2f", key=f"{sheet_name}_qty")
            
        if st.button(f"{title} 추가", key=f"{sheet_name}_add", use_container_width=True):
            u_price = db.get_unit_price(selected_item, sheet_name=sheet_name)
            new_row = pd.DataFrame([{
                "공종명": selected_item, "구분": category, "단위": default_unit, 
                "단가": u_price, "수량": qty, "합계": u_price * qty,
                "시작일": date.today(), "종료일": date.today()
            }])
            st.session_state.estimate_data = pd.concat([st.session_state.estimate_data, new_row], ignore_index=True)
            st.rerun()

@st.dialog("⚠️ 프로젝트 삭제 확인")
def delete_confirmation(project_name):
    st.error(f"**'{project_name}'** 프로젝트를 정말로 삭제하시겠습니까?\n\n삭제된 데이터는 **절대 복구할 수 없습니다.**")
    c1, c2 = st.columns(2)
    if c1.button("🔥 정말 삭제하기", use_container_width=True):
        if project_name in st.session_state.projects:
            del st.session_state.projects[project_name]
        db.delete_project_from_cloud(project_name)
        if st.session_state.projects:
            st.session_state.current_project = list(st.session_state.projects.keys())[0]
        else:
            st.session_state.projects = {"기본 프로젝트": pd.DataFrame(columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])}
            st.session_state.current_project = "기본 프로젝트"
        st.session_state.estimate_data = st.session_state.projects[st.session_state.current_project].copy()
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
