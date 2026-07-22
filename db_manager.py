import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
import pandas as pd
import os

def get_gsheet_client():
    if os.path.exists("service_account.json"):
        with open("service_account.json", "r", encoding="utf-8") as f:
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

def get_sheet():
    client = get_gsheet_client()
    return client.open_by_url(st.secrets["SPREADSHEET_URL"])

def init_db():
    try:
        doc = get_sheet()
        try: doc.worksheet("기초DB")
        except: doc.add_worksheet(title="기초DB", rows="1000", cols="10").append_row(["category_large", "category_mid", "item_name", "spec", "unit", "unit_price", "source"])
        try: doc.worksheet("프로젝트저장소")
        except: doc.add_worksheet(title="프로젝트저장소", rows="1000", cols="10").append_row(["project_name", "date", "data_json"])
    except: pass

@st.cache_data(ttl=300)
def get_filtered_master_items(category_large="전체", search_keyword=""):
    try:
        doc = get_sheet()
        ws = doc.worksheet("기초DB")
        data = ws.get_all_records()
        if not data: return pd.DataFrame(columns=["category_large", "category_mid", "item_name", "spec", "unit", "unit_price", "source"])
        df = pd.DataFrame(data)
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
        if not os.path.exists(file_path):
            return {"status": "error", "message": "엑셀 파일을 찾을 수 없습니다."}

        df = pd.read_excel(file_path).fillna("")

        df.columns = ["category_large", "category_mid", "item_name", "spec", "unit", "unit_price", "source"]

        doc = get_sheet()
        ws = doc.worksheet("기초DB")
        ws.clear()
        ws.append_row(df.columns.values.tolist())
        ws.append_rows(df.values.tolist())
        return {"status": "success", "message": "동기화 완료!"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

def get_cloud_projects_list():
    try:
        doc = get_sheet()
        ws = doc.worksheet("프로젝트저장소")
        records = ws.get_all_records()

        result = []
        for r in records:
            result.append({
                "name": str(r.get("project_name", "이름없음")),
                "date": str(r.get("date", ""))
            })
        return result
    except Exception as e:
        import streamlit as st
        st.error(f"목록을 불러오는 중 오류 발생: {e}")
        return []

def delete_project_from_cloud(project_name):
    try:
        doc = get_sheet()
        ws = doc.worksheet("프로젝트저장소")
        cells = ws.col_values(1)

        row_idx = -1
        for idx, val in enumerate(cells):
            if str(val) == str(project_name):
                row_idx = idx + 1
                break

        if row_idx != -1:
            ws.delete_rows(row_idx)
            return True
        else:
            return "클라우드에서 해당 프로젝트를 찾을 수 없습니다."
    except Exception as e:
        return str(e)

def add_single_master_item(category_large, category_mid, item_name, spec, unit, unit_price, source):
    try:
        doc = get_sheet()
        ws = doc.worksheet("기초DB")
        ws.append_row([category_large, category_mid, item_name, spec, unit, int(unit_price), source])
        return {"status": "success", "message": "성공"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def delete_master_item(item_name):
    try:
        doc = get_sheet()
        ws = doc.worksheet("기초DB")
        cell = ws.find(item_name)
        if cell:
            ws.delete_rows(cell.row)
            return {"status": "success", "message": f"'{item_name}' 항목이 구글 시트에서 성공적으로 삭제되었습니다."}
        else:
            return {"status": "error", "message": "해당 품목을 찾을 수 없습니다."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def upload_dataframe_to_master(df):
    try:
        doc = get_gsheet_client().open_by_url(st.secrets["SPREADSHEET_URL"])
        ws = doc.worksheet("기초DB")
        ws.clear()
        headers = df.columns.tolist()
        ws.append_row(headers)
        cleaned_df = df.fillna("")
        data_to_append = cleaned_df.values.tolist()
        if data_to_append:
            ws.append_rows(data_to_append)
        return {
            "status": "success",
            "message": f"🎉 총 {len(df)}건의 마스터 데이터가 순번 정렬 및 초기화 후 클라우드 DB에 완벽 동기화되었습니다!"
        }
    except Exception as e:
        return {"status": "error", "message": f"클라우드 DB 덮어쓰기 실패: {str(e)}"}