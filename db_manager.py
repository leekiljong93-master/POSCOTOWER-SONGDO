import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
import pandas as pd


def get_gsheet_client():
    # 1. 로컬 파일(service_account.json) 우선 탐색
    if os.path.exists("service_account.json"):
        with open("service_account.json", "r", encoding="utf-8") as f:
            creds_json = json.load(f)
    # 2. 파일이 없으면 Streamlit Secrets(클라우드 배포용) 사용
    else:
        try:
            creds_info = st.secrets["GOOGLE_CREDENTIALS"]
            if isinstance(creds_info, str):
                creds_json = json.loads(creds_info)
            else:
                creds_json = dict(creds_info)
        except Exception as e:
            st.error("인증 정보를 찾을 수 없습니다: service_account.json 파일을 확인하거나 Secrets 설정을 확인하세요.")
            raise e

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]

    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return gspread.authorize(creds)

def get_sheet():
    client = get_gsheet_client()
    return client.open_by_url(st.secrets["SPREADSHEET_URL"])

def init_db():
    try:
        doc = get_sheet()
        # 기초DB 탭 확인
        try: doc.worksheet("기초DB")
        except: doc.add_worksheet(title="기초DB", rows="1000", cols="10").append_row(["category_large", "category_mid", "item_name", "spec", "unit", "unit_price", "source"])
        # 프로젝트저장소 탭 확인
        try: doc.worksheet("프로젝트저장소")
        except: doc.add_worksheet(title="프로젝트저장소", rows="1000", cols="10").append_row(["project_name", "date", "data_json"])
    except: pass

def get_filtered_master_items(category_large="전체", search_keyword=""):
    try:
        doc = get_sheet()
        ws = doc.worksheet("기초DB")
        df = pd.DataFrame(ws.get_all_records())
        if df.empty: return df
        if category_large != "전체": df = df[df['category_large'] == category_large]
        if search_keyword: df = df[df['item_name'].str.contains(search_keyword, na=False)]
        return df
    except: return pd.DataFrame(columns=["category_large", "category_mid", "item_name", "spec", "unit", "unit_price", "source"])

def get_unit_price(item_name):
    try:
        df = get_filtered_master_items()
        item = df[df['item_name'] == item_name]
        return float(item.iloc[0]['unit_price']) if not item.empty else 0.0
    except: return 0.0

def sync_master_data_from_excel(file_path):
    try:
        df = pd.read_excel(file_path)
        doc = get_sheet()
        ws = doc.worksheet("기초DB")
        ws.clear()
        ws.update([df.columns.values.tolist()] + df.fillna("").values.tolist())
        return {"status": "success", "message": "동기화 완료!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}