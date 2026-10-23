"""DUARO real-time camera inspection dashboard."""

import base64
import csv
import io
import os
import time
from datetime import datetime
from pathlib import Path

import streamlit as st

from live_inspection import InspectionRuntime, create_detector, settings_from_env

ROOT = Path(__file__).parent
STEPS = ["상품 인식", "의류 펼치기", "촬영", "AI 검수", "결과 저장"]
CAMERAS = ("1번 카메라",)
DETECTOR_LABEL = "YOLO 기반"
UI_REFRESH_MS = max(250, int(os.getenv("UI_REFRESH_MS", "500")))

st.set_page_config(page_title="DUARO · 실시간 검수", page_icon="🔎", layout="wide")
st.html(f"<style>{(ROOT / 'style.css').read_text(encoding='utf-8')}</style>")


@st.cache_resource(show_spinner="카메라와 AI 모델을 연결하는 중입니다…")
def create_runtime():
    settings = settings_from_env()
    detector = create_detector(settings)
    return InspectionRuntime(
        settings["sources"], detector, settings["infer_every"], settings["simulated_names"],
        settings["open_timeout_ms"], settings["read_timeout_ms"], settings["width"],
        settings["height"], settings["requested_fps"], settings["jpeg_quality"],
        settings["confirm_frames"], settings["release_frames"]
    )


runtime = create_runtime()
if "inspection" not in st.session_state:
    st.session_state.inspection = {
        "running": False, "started_at": None, "item": 1, "detections": {}, "history": [],
        "error": None, "workflow_state": "waiting",
    }
s = st.session_state.inspection
# Preserve sessions created by an earlier dashboard version.
s.setdefault("workflow_state", "inspecting" if s.get("running") else "waiting")


def html(value):
    st.html(value)


def background_ready():
    """YOLO does not require empty-scene registration; the heuristic does."""
    return runtime.detector.backend_name != "heuristic" or runtime.detector.background_ready


def start_inspection():
    unavailable = [name for name in runtime.configured_names if not runtime.snapshot(name).connected]
    if not runtime.detector.ready or unavailable or not runtime.configured_names or not background_ready():
        details = []
        if not runtime.detector.ready:
            details.append(runtime.detector.error or "AI 모델이 준비되지 않았습니다.")
        if not runtime.configured_names:
            details.append("설정된 카메라가 없습니다.")
        elif unavailable:
            details.append(f"카메라 연결 필요: {', '.join(unavailable)}")
        if not background_ready():
            details.append("옷을 치운 뒤 빈 배경을 등록하세요.")
        s["error"] = " / ".join(details)
        return
    s["running"] = True
    s["workflow_state"] = "inspecting"
    runtime.set_inspection_active(True)
    s["started_at"] = time.time()
    s["detections"] = {}
    s["error"] = None


def finish_inspection():
    if not s["running"]:
        return
    unavailable = [name for name in runtime.configured_names if not runtime.snapshot(name).connected]
    if not runtime.detector.ready or unavailable or not runtime.configured_names:
        s["error"] = "카메라 또는 AI 연결이 끊겨 판정을 확정하지 않았습니다."
        return
    defects = sorted(s["detections"].values(), key=lambda item: item["confidence"], reverse=True)
    verdict = "불량" if defects else "정상"
    s["history"].append({
        "시간": datetime.now().isoformat(timespec="seconds"),
        "상품": f"ITEM-{s['item']:04d}",
        "판정": verdict,
        "검출": ", ".join(item["label"] for item in defects) or "없음",
        "최고 신뢰도": f"{defects[0]['confidence']:.3f}" if defects else "0.000",
    })
    s["running"] = False
    s["workflow_state"] = "completed"
    runtime.set_inspection_active(False)
    s["started_at"] = None
    s["error"] = None


def next_item():
    if s["running"]:
        finish_inspection()
    s["item"] += 1
    s["detections"] = {}
    s["workflow_state"] = "waiting"
    runtime.set_inspection_active(False)


def calibrate_empty_background():
    if s["running"]:
        s["error"] = "검수 중에는 배경을 등록할 수 없습니다."
        return
    if runtime.calibrate_background(CAMERAS[0]):
        s["detections"] = {}
        s["error"] = None
    else:
        s["error"] = "카메라 프레임을 받은 뒤 다시 시도하세요."


def record_detections(camera_name, snapshot):
    if not s["running"]:
        return
    for detection in snapshot.detections:
        key = f"{camera_name}:{detection.label}"
        previous = s["detections"].get(key)
        if previous is None or detection.confidence > previous["confidence"]:
            s["detections"][key] = {
                "camera": camera_name, "label": detection.label, "confidence": detection.confidence
            }


def current_verdict():
    if s["running"]:
        return "불량 의심" if s["detections"] else "검수 중"
    if s["history"]:
        return s["history"][-1]["판정"]
    return "대기"


html('<div class="heading"><i></i><h1>실시간 검수 대시보드</h1><span class="brand">DUARO / LIVE INSPECTION</span></div>')


@st.fragment(run_every="500ms")
def summary():
    snapshots = [runtime.snapshot(name) for name in CAMERAS]
    for name, snapshot in zip(CAMERAS, snapshots):
        record_detections(name, snapshot)
    connected = sum(snapshot.connected for snapshot in snapshots)
    configured = len(runtime.configured_names)
    status = {
        "inspecting": "검수 중",
        "completed": "검수 완료",
    }.get(s["workflow_state"], "검수 대기")
    completed = len(s["history"])
    failed = sum(row["판정"] == "불량" for row in s["history"])
    cards = [
        ("▶", "작업 상태", status, f"카메라 {connected}/{configured} · 현재 {current_verdict()}"),
        ("▤", "검수 완료", f"{completed}건", "현재 세션"),
        ("◎", "확정 불량", f"{failed}건", "실제 AI 검출 결과"),
    ]
    for col, (icon, label, value, sub) in zip(st.columns([1.5, 1, 1], gap="small"), cards):
        with col:
            html(f'<div class="metric"><div class="metric-icon blue">{icon}</div><div><label>{label}</label><strong>{value}</strong><small>{sub}</small></div></div>')
    camera_text = "연결됨" if configured and connected == configured else f"{connected}/{configured} 연결"
    detector_text = DETECTOR_LABEL if runtime.detector.ready else "설정 필요"
    html(f'<div class="connection-strip"><span>장비 연결</span><span>● 카메라 <b>{camera_text}</b></span><span>● 검출기 <b>{detector_text}</b></span><span>● 로봇 <b>미연동</b></span></div>')


summary()
left, right = st.columns([2.25, 1], gap="medium")
with left:
    @st.fragment(run_every=f"{UI_REFRESH_MS}ms")
    def live_camera():
        camera_name = CAMERAS[0]
        snapshot = runtime.snapshot(camera_name)
        record_detections(camera_name, snapshot)
        if snapshot.jpeg:
            # Rapid st.image fragment reruns can invalidate the temporary media
            # URL before the browser fetches it.  A self-contained data URL
            # keeps each displayed JPEG valid until the next refresh.
            jpeg_base64 = base64.b64encode(snapshot.jpeg).decode("ascii")
            html(
                '<div class="live-frame">'
                f'<img src="data:image/jpeg;base64,{jpeg_base64}" alt="실시간 검수 영상">'
                '</div>'
            )
            age_ms = max(0.0, (time.time() - snapshot.captured_at) * 1000)
            mode = "SIMULATION" if snapshot.simulated else "LIVE"
            display_hz = 1000.0 / UI_REFRESH_MS
            st.caption(f"{mode} · 수신 {snapshot.fps:.1f} FPS · 화면 {display_hz:.1f} Hz · 추론 {snapshot.latency_ms:.0f} ms · 프레임 지연 {age_ms:.0f} ms · 검출 {len(snapshot.detections)}개")
        else:
            st.error(snapshot.error or "카메라의 첫 프레임을 기다리는 중입니다.")
        if snapshot.model_error:
            st.warning(snapshot.model_error)
        elif runtime.detector.warning:
            st.warning(runtime.detector.warning)

    live_camera()

    @st.fragment(run_every="500ms")
    def inspection_progress():
        with st.container(border=True):
            html('<div class="section-title">검수 진행 단계</div>')
            workflow_state = s["workflow_state"]
            active = 3 if workflow_state == "inspecting" else (4 if workflow_state == "completed" else 2)
            parts = []
            for i, name in enumerate(STEPS):
                if i < active:
                    css, icon, label = "done", "✓", "완료"
                elif i == active:
                    label = "완료" if workflow_state == "completed" else (
                        "진행 중" if workflow_state == "inspecting" else "대기"
                    )
                    css, icon = "active", str(i + 1)
                else:
                    css, icon, label = "pending", str(i + 1), "대기"
                parts.append(f'<div class="step {css}"><div class="step-icon">{icon}</div><b>{name}</b><small>{label}</small></div>')
            html('<div class="process">' + "".join(parts) + "</div>")

    inspection_progress()

with right:
    with st.container(border=True):
        html('<div class="section-title">현재 상품</div><div class="product-name">반팔</div><div class="product-sub">멜란지 그레이</div>')
        html(f'<div class="product-info"><div><label>상품 ID</label><span>ITEM-{s["item"]:04d}</span></div><div><label>검수 항목</label><span>상태 보존(오염·훼손)</span></div><div><label>검수 방식</label><span>{DETECTOR_LABEL}</span></div></div>')

    @st.fragment(run_every="500ms")
    def result():
        verdict = current_verdict()
        with st.container(border=True):
            html('<div class="section-title">현재 검수 결과</div>')
            if verdict in ("불량", "불량 의심"):
                defects = sorted(s["detections"].values(), key=lambda item: item["confidence"], reverse=True)
                detail = "<br>".join(f'{d["camera"]} · {d["label"]} {d["confidence"]:.0%}' for d in defects[:4])
                html(f'<div class="result-title" style="color:#d96b32">{verdict}</div><div class="review-note">{detail}</div>')
            elif verdict == "정상":
                html('<div class="result-title" style="color:#16875d">정상</div><div class="review-note">검수 구간에서 결함이 검출되지 않았습니다.</div>')
            elif verdict == "검수 중":
                html('<div class="result-empty">◎<strong>실시간 분석 중</strong><p>카메라의 최신 프레임을<br>AI 모델이 분석하고 있습니다.</p></div>')
            else:
                html('<div class="result-empty">◎<strong>판정 대기</strong><p>카메라와 모델 상태를 확인한 뒤<br>검수를 시작하세요.</p></div>')

    result()
    with st.expander("장비 상세 상태"):
        for name in CAMERAS:
            snapshot = runtime.snapshot(name)
            detail = "연결됨" if snapshot.connected else (snapshot.error or "연결 안 됨")
            if snapshot.simulated:
                detail += " (Wi-Fi 카메라 시뮬레이션)"
            st.caption(f"{name} — {detail}")
        st.caption(f"검출기 — {DETECTOR_LABEL} · {'준비됨' if runtime.detector.ready else runtime.detector.error}")
        if runtime.detector.backend_name == "heuristic":
            state = "등록됨" if background_ready() else "등록 필요"
            st.caption(f"빈 배경 기준 — {state}")
        st.caption("로봇 — 상태 토픽 미연동")

html('<div class="toolbar-line"></div>')


@st.fragment(run_every="500ms")
def controls():
    ready = (runtime.detector.ready and bool(runtime.configured_names)
             and all(runtime.snapshot(name).connected for name in runtime.configured_names)
             and background_ready())
    c0, c1, c2, c3 = st.columns([1.25, 1, 1, 1.5], gap="small")
    with c0:
        st.button("빈 배경 등록", on_click=calibrate_empty_background,
                  disabled=s["running"] or runtime.detector.backend_name != "heuristic",
                  use_container_width=True)
    with c1:
        st.button("검수 시작", on_click=start_inspection, disabled=s["running"] or not ready,
                  use_container_width=True)
    with c2:
        st.button("판정 확정", on_click=finish_inspection, disabled=not s["running"] or not ready,
                  use_container_width=True)
    with c3:
        st.button("다음 상품", on_click=next_item, disabled=s["running"], use_container_width=True)
    if s["error"]:
        st.error(s["error"])
    elif not ready:
        if runtime.detector.backend_name == "heuristic" and not background_ready():
            st.info("옷을 화면에서 치운 뒤 ‘빈 배경 등록’을 눌러주세요.")
        else:
            st.info("설정한 카메라와 AI 모델이 준비되면 검수를 시작할 수 있습니다.")


controls()

if s["history"]:
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=["시간", "상품", "판정", "검출", "최고 신뢰도"])
    writer.writeheader()
    writer.writerows(s["history"])
    st.download_button("검수 이력 다운로드", out.getvalue().encode("utf-8-sig"),
        file_name="inspection_history.csv", mime="text/csv", use_container_width=True)

html('<div class="footer"><span>DUARO INSPECTION SYSTEM</span><span>실시간 카메라 프레임 · AI 추론 기반 판정</span></div>')
