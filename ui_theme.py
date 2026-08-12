import streamlit as st


def apply_theme() -> None:
    """앱 전체에서 쓰는 최소한의 시각 규칙만 적용한다."""
    st.markdown(
        """
        <style>
          .block-container {max-width: 1480px; padding-top: 1.6rem; padding-bottom: 2.5rem;}
          h1 {font-size: 2rem !important; margin-bottom: .25rem;}
          h2, h3 {margin-top: 1.4rem !important;}
          [data-testid="stMetric"] {
            border: 1px solid rgba(49, 51, 63, .14);
            border-radius: .55rem;
            padding: .75rem 1rem;
            background: rgba(250, 250, 250, .6);
          }
          [data-testid="stSidebar"] [data-testid="stButton"] button {
            text-align: left;
          }
          [data-testid="stDataFrame"] {border-radius: .5rem; overflow: hidden;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_guide() -> None:
    with st.sidebar.expander("처음 사용하시나요?", expanded=False):
        st.markdown(
            "1. **새 프로젝트**를 만들거나 저장본을 불러옵니다.\n"
            "2. **설계 및 원가계산**에서 품목·수량을 입력합니다.\n"
            "3. 원가계산서를 확인한 뒤 **클라우드 저장** 또는 엑셀 다운로드를 합니다."
        )
        st.caption("기초 데이터는 관리자만 수정하고, 일반 사용자는 품목 선택으로 내역을 작성하세요.")
