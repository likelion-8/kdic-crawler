import os

# ------------------------------------------------------------------------------
# 1. 백그라운드 스레드 충돌 방지 & Hugging Face 서버 통신 차단 -> 첫 로딩 길어짐 최대한 방지
# ------------------------------------------------------------------------------
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"

# 로컬 캐시 모델 사용 (서버 체크 지연 방지)
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

import time
import streamlit as st

# ------------------------------------------------------------------------------
# 2. 페이지 기본 설정 및 CSS 스타일링
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="진짜 사자 8조 챗봇",
    page_icon="🦁",
    layout="wide",
    initial_sidebar_state="expanded"
)

# UI 스타일 커스텀
st.markdown("""
    <style>
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 3rem;
    }
    .stChatMessage {
        border-radius: 12px;
        margin-bottom: 10px;
    }
    
    /* 💡 사이드바: 타이틀은 위, 초기화 버튼만 맨 아래로 고정 */
    section[data-testid="stSidebar"] > div:first-child {
        height: 100vh !important;
    }
    div[data-testid="stSidebarUserContent"] > div {
        display: flex !important;
        flex-direction: column !important;
        min-height: calc(100vh - 4rem) !important;
    }
    div[data-testid="stSidebarUserContent"] > div > div:last-child {
        margin-top: auto !important;
        padding-bottom: 1rem !important;
    }

    /* 입력창 스타일 */
    div[data-testid="stChatInput"] > div {
        border: 1.5px solid #CBD5E0 !important;
        border-radius: 10px !important;
    }
    div[data-testid="stChatInput"] > div:focus-within {
        border-color: #6C5CE7 !important;
        box-shadow: 0 0 0 1px #6C5CE7 !important;
    }

    /* 전송 버튼 비활성화 상태 */
    div[data-testid="stChatInput"] button:disabled {
        background-color: transparent !important;
        border: none !important;
    }
    div[data-testid="stChatInput"] button:disabled svg {
        fill: #CBD5E0 !important;
        color: #CBD5E0 !important;
    }

    /* 전송 버튼 활성화 상태 (보라색 박스 + 흰색 화살표) */
    div[data-testid="stChatInput"] button:enabled,
    div[data-testid="stChatInput"] button:not(:disabled) {
        background-color: #6C5CE7 !important;
        border: none !important;
        border-radius: 8px !important;
    }
    div[data-testid="stChatInput"] button:enabled svg,
    div[data-testid="stChatInput"] button:not(:disabled) svg {
        fill: #FFFFFF !important;
        color: #FFFFFF !important;
    }

    /* 전송 버튼 마우스 오버 */
    div[data-testid="stChatInput"] button:enabled:hover,
    div[data-testid="stChatInput"] button:not(:disabled):hover {
        background-color: #5A4AD1 !important;
    }
    </style>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------
# 3. Streamlit 전용 백그라운드 리소스 캐싱 & Lazy Load
# ------------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def init_rag_system():
    start_time = time.perf_counter()
    
    from retrieval import _build_engines
    from query_classifier import _get_classifier

    _build_engines()
    _get_classifier("question_type")
    _get_classifier("business_function")

    elapsed = time.perf_counter() - start_time
    return round(elapsed, 2)


# ------------------------------------------------------------------------------
# 4. 사이드바 구성
# ------------------------------------------------------------------------------
with st.sidebar:
    st.title("🦁 진짜 사자 8조")
    
    with st.spinner("검색 엔진 및 모델 로딩 중..."):
        init_time = init_rag_system()
    
    st.success("✅ 모델 준비 완료")

    # 사이드바 맨 마지막 요소이므로 자동으로 바닥으로 내려갑니다.
    if st.button("🗑️ 대화 내역 초기화", use_container_width=True):
        st.session_state.messages = []
        st.rerun()


# ------------------------------------------------------------------------------
# 5. 메인 대화 화면 및 아바타 설정
# ------------------------------------------------------------------------------
st.title("안녕하세요. 예솜 24입니다!")
st.caption("질문을 입력하시면 관련 문서를 검색하여 HyperCLOVA X 기반으로 답변을 제공합니다.")

if "messages" not in st.session_state:
    st.session_state.messages = []

# 아바타 경로
USER_AVATAR = "🦁"
BOT_AVATAR_PATH = r"C:\Users\jhw00\kdic_\kdic-crawler\data\icon_40_chatbot.png"
BOT_AVATAR = BOT_AVATAR_PATH if os.path.exists(BOT_AVATAR_PATH) else "🤖"

# 기존 대화 기록 출력
for msg in st.session_state.messages:
    avatar = USER_AVATAR if msg["role"] == "user" else BOT_AVATAR
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])


# ------------------------------------------------------------------------------
# 6. 질문 입력 및 답변 생성 처리
# ------------------------------------------------------------------------------
if prompt := st.chat_input("질문 내용을 입력해 주세요..."):
    # 1) 사용자 질문 출력 및 저장
    st.chat_message("user", avatar=USER_AVATAR).markdown(prompt)
    st.session_state.messages.append({"role": "user", "content": prompt})

    # 2) 챗봇 답변 생성
    with st.chat_message("assistant", avatar=BOT_AVATAR):
        with st.spinner("예솜이가 생각 중입니다..."):
            try:
                from pipeline import _rag_answer_traced
                res = _rag_answer_traced(prompt)
                
                # 결과값 파싱
                answer_text = ""
                if isinstance(res, dict):
                    answer_text = res.get("answer", "")
                elif isinstance(res, (tuple, list)):
                    answer_text = res[0] if len(res) > 0 else ""
                else:
                    answer_text = str(res)

                st.markdown(answer_text)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": answer_text
                })

            except Exception as e:
                error_msg = f"답변 생성 중 오류가 발생했습니다: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({
                    "role": "assistant",
                    "content": error_msg
                })