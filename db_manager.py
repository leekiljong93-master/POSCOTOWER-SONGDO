import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import json
import pandas as pd
import os
import datetime as _dt
import time

# ------------------------------------------------------------------
# 연결(커넥션) 객체는 cache_resource로 캐싱 -> open_by_url API 호출을 세션당 1회로 제한
# ------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
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


@st.cache_resource(show_spinner=False)
def get_sheet():
    """스프레드시트 핸들 자체를 캐싱. open_by_url API 호출을 세션당 1회로 줄임."""
    client = get_gsheet_client()
    return client.open_by_url(st.secrets["SPREADSHEET_URL"])


# ------------------------------------------------------------------
# 초기화는 세션당 1회만 실행 (rerun마다 실행되는 것을 방지)
# ------------------------------------------------------------------
def init_db():
    if st.session_state.get("_db_initialized"):
        return
    try:
        doc = get_sheet()
        sheet_names = ["자재비", "인건비", "장비비", "세트"]
        existing = [ws.title for ws in doc.worksheets()]  # 1콜로 전체 목록 확인
        for s_name in sheet_names:
            if s_name not in existing:
                doc.add_worksheet(title=s_name, rows="1000", cols="10").append_row(
                    ["item_name", "spec", "unit", "unit_price", "source"])
        if "프로젝트저장소" not in existing:
            doc.add_worksheet(title="프로젝트저장소", rows="1000", cols="10").append_row(
                ["project_name", "date", "data_json"])
        st.session_state["_db_initialized"] = True
    except Exception:
        pass


MASTER_SHEET_NAMES = ["자재비", "인건비", "장비비", "세트"]
MASTER_BASE_COLUMNS = ["item_name", "spec", "unit", "unit_price", "source"]


# ------------------------------------------------------------------
# 검색어를 캐시 key에서 분리: 원본 데이터만 캐싱하고, 필터링은 pandas로 로컬 처리
# -> 검색창 타이핑 시 API 재호출 없음
# ------------------------------------------------------------------
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
    """API 호출 없이 캐시된 원본에서 pandas로 필터링만 수행."""
    df = _get_master_items_raw(sheet_name)
    if search_keyword:
        df = df[df["item_name"].astype(str).str.contains(search_keyword, na=False)]
    return df


# ------------------------------------------------------------------
# 4개 시트 통합 조회: 시트별 캐시된 원본을 재사용 (추가 API 호출 없음)
# ------------------------------------------------------------------
def get_all_master_items_combined(search_keyword=""):
    all_dfs = []
    for s_name in MASTER_SHEET_NAMES:
        df = get_filtered_master_items(sheet_name=s_name, search_keyword=search_keyword)
        df = df.copy()
        df.insert(0, "구분", s_name)
        all_dfs.append(df)
    return pd.concat(all_dfs, ignore_index=True)


def _price_lookup_table():
    """단가 조회용 캐시 테이블. 매 호출마다 API 안 타도록 미리 dict화."""
    frames = [_get_master_items_raw(s) for s in MASTER_SHEET_NAMES]
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.drop_duplicates(subset=["item_name"], keep="first")
    return combined.set_index("item_name")["unit_price"].to_dict()


def get_unit_price(item_name, sheet_name=None):
    try:
        if sheet_name:
            df = _get_master_items_raw(sheet_name)
            item = df[df["item_name"] == item_name]
            if not item.empty:
                return float(item.iloc[0]["unit_price"])
            return 0.0
        price_map = _price_lookup_table()
        return float(price_map.get(item_name, 0.0))
    except Exception:
        return 0.0


@st.cache_data(ttl=120, show_spinner=False)
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
            get_cloud_projects_list.clear()
            return True
        else:
            return "클라우드에서 해당 프로젝트를 찾을 수 없습니다."
    except Exception as e:
        return str(e)


def upload_dataframe_to_master(df, sheet_name):
    """clear() + append_row() + append_rows() (3콜) -> update() 1콜로 축소."""
    try:
        doc = get_sheet()
        ws = doc.worksheet(sheet_name)
        headers = df.columns.tolist()
        cleaned_df = df.fillna("")
        values = [headers] + cleaned_df.values.tolist()

        ws.clear()
        ws.update(values, "A1")  # 헤더+데이터를 한 번의 API 호출로 기록

        _get_master_items_raw.clear()
        return {
            "status": "success",
            "message": f"'{sheet_name}' 시트에 데이터가 완벽 동기화되었습니다!"
        }
    except Exception as e:
        return {"status": "error", "message": f"클라우드 DB 덮어쓰기 실패: {str(e)}"}


def upload_combined_dataframe_to_master(df):
    try:
        doc = get_sheet()
        # 우리가 분리해서 넣을 4개의 시트 이름
        categories = ["자재비", "인건비", "장비비", "세트"]

        for cat in categories:
            # 1. 전체 데이터에서 해당 '구분'의 데이터만 쏙 빼내기
            cat_df = df[df['구분'] == cat].copy()

            # 해당 구글 시트 탭 열기 및 기존 데이터 초기화
            ws = doc.worksheet(cat)
            ws.clear()

            # 2. 헤더(열 이름) 먼저 1줄 꽂아 넣기
            columns = cat_df.columns.values.tolist()
            ws.append_row(columns)

            if cat_df.empty:
                continue

            # 🔥 3. [핵심 소화제] 데이터 5,000개씩 쪼개서 넣기 (Chunking)
            data_list = cat_df.values.tolist()
            chunk_size = 5000  # 한 번에 먹일 양 (5천 개)

            for i in range(0, len(data_list), chunk_size):
                chunk = data_list[i: i + chunk_size]
                ws.append_rows(chunk)
                time.sleep(1)  # 구글 서버가 체하지 않게 1초간 숨 쉴 틈 주기

        return {"status": "success", "message": "수만 개의 데이터가 체하지 않고 안전하게 구글 시트에 분리 저장되었습니다!"}
    except Exception as e:
        return {"status": "error", "message": f"DB 저장 중 오류 발생: {str(e)}"}


def save_project_to_cloud(project_name, df):
    try:
        doc = get_sheet()
        ws = doc.worksheet("프로젝트저장소")
        data_json = df.to_json(orient="records", force_ascii=False)
        records = ws.get_all_records()
        row_idx = -1
        for i, r in enumerate(records):
            if str(r.get("project_name", "")) == str(project_name):
                row_idx = i + 2
                break
        now_str = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if row_idx != -1:
            ws.update(f"A{row_idx}:C{row_idx}", [[project_name, now_str, data_json]])
        else:
            ws.append_row([project_name, now_str, data_json])
        get_cloud_projects_list.clear()
        return True
    except Exception as e:
        return str(e)
