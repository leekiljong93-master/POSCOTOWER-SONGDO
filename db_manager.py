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
        sheet_names = ["자재비", "인건비", "장비비", "세트"]
        for s_name in sheet_names:
            try:
                doc.worksheet(s_name)
            except:
                doc.add_worksheet(title=s_name, rows="1000", cols="10").append_row(
                    ["item_name", "spec", "unit", "unit_price", "source"])

        try:
            doc.worksheet("프로젝트저장소")
        except:
            doc.add_worksheet(title="프로젝트저장소", rows="1000", cols="10").append_row(["project_name", "date", "data_json"])
    except:
        pass


@st.cache_data(ttl=300)
def get_filtered_master_items(sheet_name="자재비", search_keyword=""):
    try:
        doc = get_sheet()
        ws = doc.worksheet(sheet_name)
        data = ws.get_all_records()
        if not data: return pd.DataFrame(columns=["item_name", "spec", "unit", "unit_price", "source"])

        df = pd.DataFrame(data)
        if search_keyword: df = df[df['item_name'].str.contains(search_keyword, na=False)]
        return df
    except:
        return pd.DataFrame(columns=["item_name", "spec", "unit", "unit_price", "source"])


def get_unit_price(item_name, sheet_name=None):
    try:
        sheets = [sheet_name] if sheet_name else ["자재비", "인건비", "장비비", "세트"]
        for s in sheets:
            df = get_filtered_master_items(sheet_name=s)
            if not df.empty:
                item = df[df['item_name'] == item_name]
                if not item.empty:
                    return float(item.iloc[0]['unit_price'])
        return 0.0
    except:
        return 0.0


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


def upload_dataframe_to_master(df, sheet_name):
    try:
        doc = get_gsheet_client().open_by_url(st.secrets["SPREADSHEET_URL"])
        ws = doc.worksheet(sheet_name)
        ws.clear()
        headers = df.columns.tolist()
        ws.append_row(headers)
        cleaned_df = df.fillna("")
        data_to_append = cleaned_df.values.tolist()
        if data_to_append:
            ws.append_rows(data_to_append)
        return {
            "status": "success",
            "message": f"'{sheet_name}' 시트에 데이터가 완벽 동기화되었습니다!"
        }
    except Exception as e:
        return {"status": "error", "message": f"클라우드 DB 덮어쓰기 실패: {str(e)}"}