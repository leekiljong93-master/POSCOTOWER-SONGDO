# -*- coding: utf-8 -*-
"""
app.py — 포타송 설계서 작성 (Ver.260730)
─────────────────────────────────────────────────────────────
탭 구성
  대시보드 / 설계·원가계산 / 일위대가 / 수량산출 / 공정표 / 설계변경 / 기초데이터

설계 원칙
  · 부가 시트(세트구성·수량산출·공정계획·변경사유)가 비어 있으면 안내만 표시하고
    기존 동작을 그대로 유지한다. 새 기능이 기존 작업을 막지 않는다.
  · 모든 쓰기는 db_manager / db_extra 를 거치며 원자적으로 처리된다.
  · 오류는 삼키지 않고 화면에 사유를 표시한다.
  · 편집 권한(auth.py)은 선택 사항이다. 파일이 없으면 전원 편집 가능으로 동작한다.
"""

import streamlit as st

import config
import db_manager as db
import db_extra as dbx
import state_manager as state
import ui_components as ui
import ui_tabs
import ui_theme as theme

log = config.get_logger("app")

# auth.py가 없으면 기존처럼 누구나 편집할 수 있다.
# 단, auth.py가 존재하지만 정상 동작하지 않으면 안전을 위해 앱을 중지한다.
try:
    import auth
    _AUTH = True
    _AUTH_ERROR = None
except ModuleNotFoundError as exc:
    if exc.name != "auth":
        raise
    auth = None
    _AUTH = False
    _AUTH_ERROR = None
except Exception as exc:
    auth = None
    _AUTH = True
    _AUTH_ERROR = exc


def can_edit() -> bool:
    """편집 권한 오류는 허용하지 않고 잠금 상태로 처리한다."""
    if not _AUTH:
        return True
    try:
        return auth.can_edit()
    except Exception:
        log.exception("권한 확인 실패 — 편집 잠금으로 처리")
        return False


def require_edit(action: str) -> bool:
    if can_edit():
        return True
    st.warning(f"{action}은 편집 권한이 필요합니다. 사이드바에서 잠금을 해제하세요.")
    return False


def audit(action: str, detail: str = "") -> None:
    if _AUTH:
        try:
            auth.audit(action, detail)
        except Exception:
            log.exception("감사 로그 기록 실패")


# ═══════════════════════════════════════════════════════════
# 1. 페이지 설정 및 초기화
# ═══════════════════════════════════════════════════════════
st.set_page_config(page_title=config.PAGE_TITLE, page_icon=config.PAGE_ICON,
                   layout="wide")
st.title(config.APP_TITLE)
theme.apply_theme()

if _AUTH_ERROR:
    st.error("편집 권한 모듈을 불러오지 못했습니다. 보안을 위해 앱을 시작하지 않습니다.")
    st.caption(f"상세 사유: {type(_AUTH_ERROR).__name__} - {_AUTH_ERROR}")
    st.stop()

init_result = db.init_db()
if not init_result:
    st.error("Google Sheets에 연결할 수 없습니다.")
    st.caption(f"상세 사유: {init_result.message}")
    st.info("관리자에게 다음을 확인해 달라고 요청하세요: "
            "Streamlit secrets의 GOOGLE_CREDENTIALS·SPREADSHEET_URL, "
            "서비스 계정의 스프레드시트 편집 권한, Google Sheets API 활성화 여부.")
    st.stop()

state.bootstrap()
state.session_id()
extra_init_result = dbx.ensure_sheets()
if not extra_init_result:
    st.warning(f"부가 데이터 시트 준비 실패: {extra_init_result.message}")


def show_errors() -> None:
    """읽기 단계에서 발생한 오류를 사용자에게 알린다."""
    messages = list(db.consume_load_errors()) + list(dbx.consume_load_errors())
    for message in messages:
        st.warning(f"데이터 조회 경고: {message}")


# ═══════════════════════════════════════════════════════════
# 2. 사이드바
# ═══════════════════════════════════════════════════════════
theme.render_sidebar_guide()
st.sidebar.subheader("프로젝트 작업")

new_project = st.sidebar.text_input("새 프로젝트명 입력",
                                    placeholder="예: 포스코타워-송도 환경개선")
if st.sidebar.button("새 프로젝트 생성", use_container_width=True):
    ok, message = state.create_project(new_project)
    if ok:
        st.rerun()
    else:
        st.sidebar.warning(message)

names = state.project_names()
selected_project = st.sidebar.selectbox("현재 작업 중인 현장 선택", names,
                                        index=names.index(state.current_project()))
if selected_project != state.current_project():
    state.switch_project(selected_project)
    st.rerun()

if st.sidebar.button("현재 프로젝트 삭제", use_container_width=True):
    if require_edit("현재 프로젝트 삭제"):
        ui.delete_confirmation(state.current_project())

st.sidebar.divider()
st.sidebar.subheader("문서 작성 정보")
st.sidebar.text_input("작성자 / 부서",
                      value=st.session_state.get("writer_name", "포스코타워-송도 (이름/직급)"),
                      key="writer_name",
                      help="견적서 엑셀 상단 제목 블록에 표기됩니다.")

st.sidebar.divider()
st.sidebar.subheader("클라우드 DB 보관소")

if st.sidebar.button("클라우드 목록 갱신/조회", use_container_width=True):
    with st.spinner("구글 시트에서 불러오는 중..."):
        db.get_cloud_projects_list.clear()
        st.session_state.cloud_project_list = db.get_cloud_projects_list()

selected_cloud = None
if st.session_state.cloud_project_list:
    options = {f"{p['name']} ({p['date']})": p["name"]
               for p in st.session_state.cloud_project_list}
    selected_cloud = options[st.sidebar.selectbox("불러올 프로젝트 선택",
                                                  list(options.keys()))]

    if st.sidebar.button("선택 프로젝트 불러오기", use_container_width=True):
        with st.spinner(f"'{selected_cloud}' 데이터를 가져오는 중..."):
            result = db.load_project_from_cloud(selected_cloud)
        if result:
            loaded_df, version = result.data
            state.replace_project(selected_cloud, loaded_df, version=version)
            st.rerun()
        else:
            st.sidebar.error(result.message)

    if st.sidebar.button("클라우드에서 삭제", use_container_width=True):
        if require_edit("클라우드 삭제"):
            ui.delete_cloud_confirmation(selected_cloud)

if st.sidebar.button("현재 프로젝트 클라우드 저장", use_container_width=True,
                     type="primary"):
    if require_edit("클라우드 저장"):
        project = state.current_project()
        with st.spinner("기록 중..."):
            result = db.save_project_to_cloud(
                project, state.get_estimate(),
                expected_version=state.get_version(project))
        if result:
            state.set_version(project, result.data)
            audit("프로젝트 저장", project)
            st.sidebar.success("클라우드 저장 완료!")
        elif result.code == "conflict":
            ui.overwrite_conflict_dialog(project, str(result.data))
        else:
            st.sidebar.error(result.message)

if _AUTH:
    try:
        auth.render_sidebar_login()
    except Exception:
        log.exception("권한 위젯 표시 실패")

show_errors()



ui_tabs.render(
    can_edit=can_edit,
    require_edit=require_edit,
    audit=audit,
    show_errors=show_errors,
)
