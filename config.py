import streamlit as st
import pandas as pd

APP_TITLE = "🏗️ 포타송 설계서 작성(by.PI_Lee)"
PAGE_TITLE = "포타송 설계서 작성(Ver.260720)"
PAGE_ICON = "🏗️"

MASTER_SHEET_NAMES = ["자재비", "인건비", "장비비", "세트"]
MASTER_BASE_COLUMNS = ["item_name", "spec", "unit", "unit_price", "source"]

# 조달청 기준 기본 제비율(%) 설정
DEFAULT_RATES = {
    'indirect_labor': 14.5,
    'sanjae': 3.7,
    'goyong': 1.15,
    'health': 3.545,
    'elderly': 12.95,
    'pension': 4.5,
    'retire': 2.31,
    'safety': 1.86,
    'env': 0.9,
    'etc_exp': 5.5,
    'general_admin': 5.0,
    'profit': 10.0,
    'tax': 10.0
}

def init_session_state():
    """앱 구동 시 필요한 Session State 초기화 및 동기화"""
    if 'projects' not in st.session_state:
        st.session_state.projects = {
            "기본 프로젝트": pd.DataFrame(columns=["공종명", "구분", "단위", "단가", "수량", "합계", "시작일", "종료일"])
        }
        st.session_state.current_project = "기본 프로젝트"
        st.session_state.estimate_data = st.session_state.projects["기본 프로젝트"].copy()
        st.session_state.cloud_project_list = []

    # 상태 동기화
    if 'current_project' in st.session_state and 'estimate_data' in st.session_state:
        st.session_state.projects[st.session_state.current_project] = st.session_state.estimate_data.copy()
