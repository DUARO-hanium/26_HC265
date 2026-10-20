"""DUARO dashboard driven by two saved inspection videos."""
import csv, io, time
from datetime import datetime
from pathlib import Path
import streamlit as st

ROOT = Path(__file__).parent
STEPS = ["상품 인식", "의류 펼치기", "촬영", "AI 검수", "결과 저장"]
CAMERAS = ("1번 카메라", "2번 카메라")
VIDEOS = {name: ROOT / "videos" / f"camera_{i}.mp4" for i, name in enumerate(CAMERAS, 1)}
DURATIONS = {"1번 카메라": 162.208, "2번 카메라": 180.467}
BBOX_AT = 89.0

st.set_page_config(page_title="DUARO · 실시간 검수", page_icon="🔎", layout="wide")
st.html(f"<style>{(ROOT / 'style.css').read_text(encoding='utf-8')}</style>")
if "inspection_v3" not in st.session_state:
    st.session_state.inspection_v3 = {"camera1_started_at": time.time(), "camera2_started_at": None, "item": 1}
if "selected_camera" not in st.session_state:
    st.session_state.selected_camera = CAMERAS[0]
s = st.session_state.inspection_v3

def html(value): st.html(value)

def elapsed1(): return max(0.0, time.time() - s["camera1_started_at"])
def camera1_done(): return elapsed1() >= DURATIONS[CAMERAS[0]]

def maybe_start_camera2():
    if st.session_state.selected_camera == CAMERAS[1] and camera1_done() and s["camera2_started_at"] is None:
        s["camera2_started_at"] = time.time()

def flow():
    if s["camera2_started_at"] is not None:
        return "complete" if time.time() - s["camera2_started_at"] >= DURATIONS[CAMERAS[1]] else "camera2"
    if camera1_done(): return "review"
    return "camera1" if elapsed1() >= BBOX_AT else "preparation"

def render_camera():
    path = VIDEOS[st.session_state.selected_camera]
    if path.is_file():
        st.video(path, format="video/mp4", loop=False, autoplay=True, muted=True)
    else:
        st.error(f"{path.name} 파일을 videos 폴더에 넣어주세요.")

@st.dialog("검수 영상 확대", width="large")
def enlarge(): render_camera()

def reset_flow():
    st.session_state.inspection_v3 = {"camera1_started_at": time.time(), "camera2_started_at": None, "item": 1}
    st.session_state.selected_camera = CAMERAS[0]

maybe_start_camera2()
html('<div class="heading"><i></i><h1>실시간 검수 대시보드</h1><span class="brand">DUARO / INSPECTION</span></div>')

@st.fragment(run_every="1s")
def summary():
    state = flow()
    status = {"preparation":"영상 확인 중", "camera1":"검수 진행 중", "review":"추가 확인 필요", "camera2":"검수 진행 중", "complete":"검수 완료"}[state]
    note = {"preparation":"바운딩박스 검출 대기", "camera1":"1번 카메라 · 바운딩박스 검출", "review":"2번 카메라 영상을 확인하세요", "camera2":"2번 카메라 · 추가 검수", "complete":"두 영상 확인 및 결과 저장 완료"}[state]
    done = int(state == "complete")
    for col, (icon, label, value, sub) in zip(st.columns([1.5,1,1], gap="small"), [
        ("▶","작업 상태",status,note), ("▤","검수 완료",f"{done}건","현재 세션"), ("◎","확정 불량",f"{done}건","두 영상 확인 결과")]):
        with col: html(f'<div class="metric"><div class="metric-icon blue">{icon}</div><div><label>{label}</label><strong>{value}</strong><small>{sub}</small></div></div>')
summary()

html('<div class="connection-strip"><span>장비 연결</span><span>● 로봇 <b>연결됨</b></span><span>● 카메라 <b>연결됨</b></span><span>● AI <b>연결됨</b></span></div>')
left, right = st.columns([2.25,1], gap="medium")
with left:
    st.radio("카메라 선택", CAMERAS, horizontal=True, key="selected_camera")
    maybe_start_camera2()
    render_camera()
    _, zoom = st.columns([3,1])
    with zoom:
        if st.button("⛶ 영상 확대", use_container_width=True): enlarge()

    @st.fragment(run_every="1s")
    def process():
        state = flow(); active = 4 if state == "complete" else 3
        with st.container(border=True):
            html('<div class="section-title">검수 진행 단계</div>')
            parts = []
            for i, name in enumerate(STEPS):
                if i < active: css, icon, label = "done", "✓", "완료"
                elif i == active: css, icon, label = "active", str(i+1), "완료" if state == "complete" else "진행 중"
                else: css, icon, label = "pending", str(i+1), "대기"
                parts.append(f'<div class="step {css}"><div class="step-icon">{icon}</div><b>{name}</b><small>{label}</small></div>')
            html('<div class="process">'+''.join(parts)+'</div>')
    process()

with right:
    with st.container(border=True):
        html('<div class="section-title">현재 상품</div><div class="product-name">반팔</div><div class="product-sub">멜란지 그레이</div>')
        html(f'<div class="product-info"><div><label>상품 ID</label><span>DEMO-{s["item"]:04d}</span></div><div><label>검수 사유</label><span>이염 의심</span></div></div>')

    @st.fragment(run_every="1s")
    def result():
        state = flow()
        with st.container(border=True):
            html('<div class="section-title">현재 검수 결과</div>')
            if state == "complete":
                html('<div class="result-title" style="color:#d96b32">불량</div><div class="review-note">검수 완료<br><small>1번·2번 카메라 영상 확인 및 결과 저장 완료</small></div><div class="score-row"><span>최종 결과</span><b>확정 불량</b></div>')
            elif state == "review":
                html('<div class="result-title" style="color:#e28a24">추가 확인 필요</div><div class="review-note">1번 영상 재생 완료<br><small>2번 카메라를 선택해 추가 영상을 확인하세요.</small></div>')
            elif state in ("camera1","camera2"):
                html('<div class="result-empty">◎<strong>검수 진행 중</strong><p>바운딩박스가 포함된 영상을<br>분석하고 있습니다.</p></div>')
            else:
                html('<div class="result-empty">◎<strong>판정 대기</strong><p>바운딩박스가 나타나면<br>검수를 시작합니다.</p></div>')
    result()
    with st.expander("장비 상세 상태"):
        for name in ["왼팔","오른팔","그리퍼","Z축 리프트","1번 카메라","2번 카메라","AI 모델"]:
            st.caption(f"{name} — 연결됨")

html('<div class="toolbar-line"></div>')
c1, c2 = st.columns([1,2], gap="small")
with c1: st.button("처음부터 다시 보기", on_click=reset_flow, use_container_width=True)
with c2:
    @st.fragment(run_every="1s")
    def download():
        if flow() == "complete":
            out=io.StringIO(newline=""); writer=csv.DictWriter(out,fieldnames=["시간","상품","판정","판정방식"]); writer.writeheader()
            writer.writerow({"시간":datetime.now().isoformat(timespec="seconds"),"상품":"DEMO-0001","판정":"불량","판정방식":"2개 영상 확인"})
            st.download_button("검수 이력 다운로드",out.getvalue().encode("utf-8-sig"),file_name="inspection_history.csv",mime="text/csv",use_container_width=True)
        else: st.button("검수 이력 다운로드",disabled=True,use_container_width=True)
    download()
html('<div class="footer"><span>DUARO INSPECTION SYSTEM</span><span>영상 재생 시간 기준 자동 상태 전환</span></div>')
