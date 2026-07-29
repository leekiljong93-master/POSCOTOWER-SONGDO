import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
import pandas as pd
import os
import datetime as _dt
import time
from config import MASTER_SHEET_NAMES, MASTER_BASE_COLUMNS

@st.cache_resource(show_spinner=False)
def get_gsheet_client():
    if os.path.exists("service_account.json"):
        with open("service_account.json", "r", encoding="utf-utf-8" if False else "utf-8") as f:
            creds_json = json.load(f)
    else:
        try:
            creds_info = st.secrets["GOOGLE_CREDENTIALS"]
            creds_json = dict(creds_info)
        except Exception as e:
            st.error(f"인증 정보 로드 실패: {e}")
            raise e

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return gspread.authorize(creds)

@st.cache_resource(show_spinner=False)
def get_sheet():
    client = get_gsheet_client()
    return client.open_by_url(st.secrets["SPREADSHEET_URL"])

def init_db():
    if st.session_state.get("_db_initialized"):
        return
    try:
        doc = get_sheet()
        existing = [ws.title for ws in doc.worksheets()]
        for s_name in MASTER_SHEET_NAMES:
            if s_name not in existing:
                doc.add_worksheet(title=s_name, rows="1000", cols="10").append_row(MASTER_BASE_COLUMNS)
        if "프로젝트저장소" not in existing:
            doc.add_worksheet(title="프로젝트저장소", rows="1000", cols="10").append_row(
                ["project_name", "date", "data_json"])
        st.session_state["_db_initialized"] = True
    except Exception:
        pass

@st.cache_data(ttl=600, show_spinner=False)
def _get_master_items_raw(sheet_name):
    try:
        doc = get_sheet()
        ws = doc.worksheet(sheet_name)
        data = ws.get_all_records()
        if not data:
            return pd.DataFrame(columns=MASTER_BASE_COLUMNS)
        df = pd.DataFrame(data)
        for c in MASTER_BASE_COLUMNS:
            if c not in df.columns:
                df[c] = ""
        return df[MASTER_BASE_COLUMNS]
    except Exception:
        return pd.DataFrame(columns=MASTER_BASE_COLUMNS)

def get_filtered_master_items(sheet_name="자재비", search_keyword=""):
    df = _get_master_items_raw(sheet_name)
    if search_keyword:
        df = df[df["item_name"].astype(str).str.contains(search_keyword, na=False)]
    return df

def get_all_master_items_combined(search_keyword=""):
    all_dfs = []
    for s_name in MASTER_SHEET_NAMES:
        df = get_filtered_master_items(sheet_name=s_name, search_keyword=search_keyword).copy()
        df.insert(0, "구분", s_name)
        all_dfs.append(df)
    return pd.concat(all_dfs, ignore_index=True)

def get_unit_price(item_name, sheet_name=None):
    try:
        if sheet_name:
            df = _get_master_items_raw(sheet_name)
            item = df[df["item_name"] == item_name]
            return float(item.iloc[0]["unit_price"]) if not item.empty else 0.0
        
        frames = [_get_master_items_raw(s) for s in MASTER_SHEET_NAMES]
        combined = pd.concat(frames, ignore_index=True).drop_duplicates(subset=["item_name"], keep="first")
        price_map = combined.set_index("item_name")["unit_price"].to_dict()
        return float(price_map.get(item_name, 0.0))
    except Exception:
        return 0.0

@st.cache_data(ttl=120, show_spinner=False)
def get_cloud_projects_list():
    try:
        ws = get_sheet().worksheet("프로젝트저장소")
        records = ws.get_all_records()
        return [{"name": str(r.get("project_name", "이름없음")), "date": str(r.get("date", ""))} for r in records]
    except Exception as e:
        st.error(f"목록을 불러오는 중 오류 발생: {e}")
        return []

def delete_project_from_cloud(project_name):
    try:
        ws = get_sheet().worksheet("프로젝트저장소")
        cells = ws.col_values(1)
        if str(project_name) in cells:
            ws.delete_rows(cells.index(str(project_name)) + 1)
            get_cloud_projects_list.clear()
            return True
        return "클라우드에서 해당 프로젝트를 찾을 수 없습니다."
    except Exception as e:
        return str(e)

def save_project_to_cloud(project_name, df):
    try:
        ws = get_sheet().worksheet("프로젝트저장소")
        data_json = df.to_json(orient="records", force_ascii=False)
        records = ws.get_all_records()
        
        row_idx = next((i + 2 for i, r in enumerate(records) if str(r.get("project_name", "")) == str(project_name)), -1)
        now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        if row_idx != -1:
            ws.update(f"A{row_idx}:C{row_idx}", [[project_name, now_str, data_json]])
        else:
            ws.append_row([project_name, now_str, data_json])
        
        get_cloud_projects_list.clear()
        return True
    except Exception as e:
        return str(e)

def upload_combined_dataframe_to_master(df):
    try:
        doc = get_sheet()
        for cat in MASTER_SHEET_NAMES:
            cat_df = df[df['구분'] == cat].copy()
            ws = doc.worksheet(cat)
            ws.clear()
            ws.append_row(cat_df.columns.values.tolist())

            if cat_df.empty:
                continue

            data_list = cat_df.fillna("").values.tolist()
            chunk_size = 5000

            for i in range(0, len(data_list), chunk_size):
                ws.append_rows(data_list[i: i + chunk_size])
                time.sleep(1)
                
        _get_master_items_raw.clear()
        return {"status": "success", "message": "수만 개의 데이터가 체하지 않고 안전하게 구글 시트에 분리 저장되었습니다!"}
    except Exception as e:
        return {"status": "error", "message": f"DB 저장 중 오류 발생: {str(e)}"}
