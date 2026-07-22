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


# ------------------------------------------------------------------
# 4개 시트(자재비/인건비/장비비/세트)를 하나의 DataFrame으로 통합 조회
# ------------------------------------------------------------------
MASTER_SHEET_NAMES = ["자재비", "인건비", "장비비", "세트"]
MASTER_BASE_COLUMNS = ["item_name", "spec", "unit", "unit_price", "source"]


@st.cache_data(ttl=300)
def get_all_master_items_combined(search_keyword=""):
    """4개 기초데이터 시트를 하나의 표로 합쳐서 반환. 맨 앞에 '구분' 컬럼 추가."""
    all_dfs = []
    for s_name in MASTER_SHEET_NAMES:
        df = get_filtered_master_items(sheet_name=s_name, search_keyword=search_keyword)

        if df.empty:
            df = pd.DataFrame(columns=MASTER_BASE_COLUMNS)
        else:
            # 누락된 컬럼은 빈 값으로 채우고, 컬럼 순서 통일
            for c in MASTER_BASE_COLUMNS:
                if c not in df.columns:
                    df[c] = ""
            df = df[MASTER_BASE_COLUMNS].copy()

        df.insert(0, "구분", s_name)
        all_dfs.append(df)

    combined = pd.concat(all_dfs, ignore_index=True)
    return combined


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


# ------------------------------------------------------------------
# 통합 표(구분 컬럼 포함)를 받아서 4개 시트로 자동 분배 업로드
# ------------------------------------------------------------------
def upload_combined_dataframe_to_master(df):
    try:
        df = df.copy()

        # 필수 컬럼 보정
        for c in ["구분"] + MASTER_BASE_COLUMNS:
            if c not in df.columns:
                df[c] = ""

        df["구분"] = df["구분"].astype(str).str.strip()

        saved_sheets = []
        for s_name in MASTER_SHEET_NAMES:
            sub_df = df[df["구분"] == s_name].copy()
            sub_df = sub_df[MASTER_BASE_COLUMNS]

            res = upload_dataframe_to_master(sub_df, s_name)
            if res["status"] != "success":
                return {"status": "error", "message": f"[{s_name}] 저장 실패: {res['message']}"}
            saved_sheets.append(f"{s_name}({len(sub_df)}건)")

        get_filtered_master_items.clear()
        get_all_master_items_combined.clear()

        return {
            "status": "success",
            "message": "저장 완료! → " + ", ".join(saved_sheets)
        }
    except Exception as e:
        return {"status": "error", "message": f"통합 저장 중 오류 발생: {str(e)}"}
