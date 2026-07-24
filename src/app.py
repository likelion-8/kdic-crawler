"""pip install -r requirements.txt 및 `streamlit run src/app.py` 명령어 실행"""
import os
import re
import time
import base64
import html
import requests
import streamlit as st

# ------------------------------------------------------------------------------
# 1. 환경변수
# ------------------------------------------------------------------------------
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OMP_NUM_THREADS"] = "1"
os.environ["MKL_NUM_THREADS"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_OFFLINE"] = "1"

# ------------------------------------------------------------------------------
# 2. 페이지 설정 및 최소한의 커스텀 CSS (Streamlit 순정 테마 기능 살리기)
# ------------------------------------------------------------------------------
st.set_page_config(
    page_title="진짜 사자 8조 챗봇",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Noto+Sans+KR:wght@400;600;700&display=swap');

* { font-family: 'Noto Sans KR', sans-serif; }

/* ==========================================================================
   🎨 [여기서 원하는 색상 코드(#HEX)를 직접 변경해 보세요!]
   ========================================================================== */
:root {

    --my-point-color: #7E57C2;     


    --input-focus-border: #7E57C2;   /* 입력할 때 감싸는 테두리 색상 */

    /* 3. 텍스트 입력 시 반응하는 전송 버튼 및 화살표 색상 */
    --button-bg: #7E57C2;           /* 전송 버튼 배경색 */
    --button-hover-bg: #512DA8;     /* 마우스 올렸을 때 버튼 색상 */
    --button-arrow-color: #FFFFFF;  /* 화살표 아이콘 색상 */
}

/* ==========================================================================
   🛠️ 시스템 모드(라이트/다크) 안정화 CSS
   ========================================================================== */

/* ── 레이아웃 여백 ── */
.main .block-container {
    padding-top: 1rem !important;
    padding-bottom: 2rem !important;
    max-width: 820px !important;
}

/* ── 1. "진짜사자챗봇" 글자색 적용 ── */
.welcome-text span { 
    color: var(--my-point-color) !important; 
}

/* ── 2. 입력창 기본 & 입력 중(Focus) 테두리 (빨간색 방지) ── */
[data-testid="stChatInput"] {
    max-width: 720px !important;
    margin: 0 auto !important;
}

/* 글자 입력 중 클릭되었을 때 나오는 테두리 반응색 변경 */
[data-testid="stChatInput"] > div:focus-within {
    border-color: var(--input-focus-border) !important;
    box-shadow: 0 0 0 1px var(--input-focus-border) !important;
}

/* ── 3. 전송 버튼 & 화살표 아이콘 색상 ── */
[data-testid="stChatInputSubmitButton"] button {
    background-color: var(--button-bg) !important;
    border: none !important;
    border-radius: 10px !important;
}
[data-testid="stChatInputSubmitButton"] button:hover {
    background-color: var(--button-hover-bg) !important;
}
[data-testid="stChatInputSubmitButton"] button svg,
[data-testid="stChatInputSubmitButton"] button svg path {
    fill: var(--button-arrow-color) !important;
    stroke: var(--button-arrow-color) !important;
    color: var(--button-arrow-color) !important;
}

/* ===================== 웰컴 화면 ===================== */
.welcome-screen {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 65vh;
    gap: 20px;
}
.welcome-icon svg {
    width: 72px !important;
    height: 72px !important;
    display: block;
}
.welcome-text {
    font-size: 2rem;
    font-weight: 700;
    color: var(--text-color); /* Streamlit 다크/라이트 자동 감지 */
    letter-spacing: -0.5px;
    line-height: 1.3;
    text-align: center;
}

/* ===================== 채팅 화면 ===================== */
.chat-screen {
    width: 100%;
    padding: 1rem 0 4rem;
}
.chat-row {
    display: flex;
    align-items: flex-start;
    margin-bottom: 14px;
    gap: 10px;
}
.chat-row.bot  { justify-content: flex-start; }
.chat-row.user { justify-content: flex-end; }

.chat-avatar {
    width: 38px;
    height: 38px;
    border-radius: 50%;
    overflow: hidden;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background-color: var(--secondary-background-color);
}
.chat-avatar svg {
    width: 100% !important;
    height: 100% !important;
    display: block;
}

.chat-bubble {
    padding: 11px 15px;
    line-height: 1.6;
    font-size: 0.95rem;
    max-width: 68%;
    width: fit-content;
    word-wrap: break-word;
    white-space: pre-wrap;
}

/* 챗봇 말풍선 (시스템 테마 배경 및 글자색 자동 적용) */
.chat-bubble.bot {
    background-color: var(--secondary-background-color);
    color: var(--text-color);
    border: 1px solid rgba(128, 128, 128, 0.2);
    border-radius: 4px 18px 18px 18px;
}   

/* 사용자 말풍선 */
.chat-bubble.user {
    background-color: #FEE500;
    color: #191919;
    border-radius: 18px 4px 18px 18px;
}
</style>

<script>
(function() {
    function removeSpellcheck() {
        document.querySelectorAll('textarea').forEach(function(el) {
            el.setAttribute('spellcheck', 'false');
        });
    }
    removeSpellcheck();
    new MutationObserver(removeSpellcheck).observe(document.body, { childList: true, subtree: true });
})();
</script>
""", unsafe_allow_html=True)


# ------------------------------------------------------------------------------
# 3. iconify SVG 로드
# ------------------------------------------------------------------------------
BOT_ICON        = "noto:robot"
USER_ICON       = "noto:lion"
BOT_AVATAR_PATH = r"C:\Users\jhw00\kdic_\kdic-crawler\data\icon_40_chatbot.png"

def get_base64_image(file_path):
    if os.path.exists(file_path):
        with open(file_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode()
        return f"data:image/png;base64,{encoded}"
    return None

def fetch_iconify_svg(icon_name, size=38):
    url = f"https://api.iconify.design/{icon_name}.svg"
    try:
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        svg = resp.text
        svg = re.sub(r'\s+width=["\'][^"\'> ]*["\']',  '', svg)
        svg = re.sub(r'\s+height=["\'][^"\'> ]*["\']', '', svg)
        return svg.replace('<svg', f'<svg width="{size}" height="{size}"', 1)
    except Exception:
        return None

@st.cache_resource(show_spinner=False)
def load_avatars():
    bot_local   = get_base64_image(BOT_AVATAR_PATH)
    bot_svg     = fetch_iconify_svg(BOT_ICON,  size=38) if not bot_local else None
    user_svg    = fetch_iconify_svg(USER_ICON, size=38)
    welcome_svg = fetch_iconify_svg(USER_ICON, size=72)
    return bot_local, bot_svg, user_svg, welcome_svg

BOT_LOCAL_IMG, BOT_SVG, USER_SVG, WELCOME_SVG = load_avatars()


# ------------------------------------------------------------------------------
# 4. RAG 시스템 및 세션 초기화
# ------------------------------------------------------------------------------
@st.cache_resource(show_spinner=False)
def init_rag_system():
    start_time = time.perf_counter()
    from retrieval import _build_engines
    from query_classifier import _get_classifier
    _build_engines()
    _get_classifier("question_type")
    _get_classifier("business_function")
    return round(time.perf_counter() - start_time, 2)

init_rag_system()

if "messages" not in st.session_state:
    st.session_state.messages = []


# ------------------------------------------------------------------------------
# 5. 렌더링 함수
# ------------------------------------------------------------------------------
def make_avatar_html(role):
    if role == "user":
        return f'<div class="chat-avatar">{USER_SVG if USER_SVG else "🦁"}</div>'
    else:
        if BOT_LOCAL_IMG:
            return f'<div class="chat-avatar"><img src="{BOT_LOCAL_IMG}" style="width:100%;height:100%;object-fit:cover;border-radius:50%;" /></div>'
        return f'<div class="chat-avatar">{BOT_SVG if BOT_SVG else "🤖"}</div>'

def render_message(role, content):
    safe = html.escape(content).replace("\n", "<br>")
    cls  = "user" if role == "user" else "bot"
    av   = make_avatar_html(role)
    if role == "user":
        return f'<div class="chat-row {cls}"><div class="chat-bubble {cls}">{safe}</div>{av}</div>'
    else:
        return f'<div class="chat-row {cls}">{av}<div class="chat-bubble {cls}">{safe}</div></div>'


# ------------------------------------------------------------------------------
# 6. 화면 렌더링
# ------------------------------------------------------------------------------
is_chatting = len(st.session_state.messages) > 0

if not is_chatting:
    welcome_icon = f'<div class="welcome-icon">{WELCOME_SVG}</div>' if WELCOME_SVG else '<div style="font-size:72px;text-align:center">🦁</div>'
    st.markdown(f"""
    <div class="welcome-screen">
        {welcome_icon}
        <div class="welcome-text">
            <span>진짜 사자 8조 챗봇</span>에 오신 걸 환영해요
        </div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown('<div class="chat-screen">', unsafe_allow_html=True)
    for msg in st.session_state.messages:
        st.markdown(render_message(msg["role"], msg["content"]), unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


# ------------------------------------------------------------------------------
# 7. 입력창 및 답변 생성
# ------------------------------------------------------------------------------
placeholder = "예솜이가 어떤 일을 도와드릴까요?" if not is_chatting else "질문을 입력해 주세요..."

if prompt := st.chat_input(placeholder):
    st.session_state.messages.append({"role": "user", "content": prompt})
    st.rerun()

if st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
    user_prompt = st.session_state.messages[-1]["content"]
    with st.spinner("예솜이가 생각 중입니다..."):
        try:
            from pipeline import _rag_answer_traced
            res = _rag_answer_traced(user_prompt)
            if isinstance(res, dict):
                answer_text = res.get("answer", "")
            elif isinstance(res, (tuple, list)):
                answer_text = res[0] if len(res) > 0 else ""
            else:
                answer_text = str(res)
            st.session_state.messages.append({"role": "assistant", "content": answer_text})
        except Exception as e:
            st.session_state.messages.append({"role": "assistant", "content": f"답변 생성 중 오류가 발생했습니다: {str(e)}"})
    st.rerun()