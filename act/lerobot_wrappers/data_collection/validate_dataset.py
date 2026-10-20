#!/usr/bin/env python3
"""LeRobotDataset 사후 검증 — 녹화 직후 데이터가 학습에 쓸 수 있는 상태인지 판정.

record.sh가 녹화 종료 후 자동 호출하며 단독 실행도 가능:
  python validate_dataset.py ~/duaro_data/omx_garment_pick

검사 항목 (에피소드별 PASS/WARN/FAIL):
  1. 파일 존재      — parquet, 카메라별 mp4가 메타(episodes.jsonl)와 일치
  2. 프레임 수 일치 — parquet 행 수 == 메타 length == 각 mp4 프레임 수
  3. 값 건전성      — action/observation.state에 NaN 없음, 전 구간 상수(멈춘 센서) 없음
  4. 캡처율 추정    — usbipd fps 붕괴("1분 촬영→1초 영상") 검출

주의: parquet의 timestamp 컬럼은 frame_index/fps로 계산된 값이라 실제 캡처
fps 문제를 드러내지 못한다 (2fps로 망가진 데이터도 timestamp는 완벽한 30fps로
보임 — 실제 사고로 확인됨). 그래서 4번은 연속된 에피소드 mp4 파일 mtime 간격
(실제 벽시계 시간의 상한)과 저장된 프레임 수를 대조하는 휴리스틱을 쓴다.
간격에는 reset 시간과 인코딩 시간이 섞여 있어 정확한 fps는 아니므로,
극단적인 비율(기본 0.15 미만)일 때만 FAIL로 판정한다.

실패 에피소드는 자동 삭제·이동하지 않는다 — LeRobotDataset은 메타에 인덱스가
얽혀 있어 파일만 옮기면 데이터셋이 깨진다. 재녹화 권고까지만 하고 처리는
사람이 결정한다.
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

try:
    import cv2
except ImportError:  # mp4 프레임 수 검사만 건너뛰고 나머지는 수행
    cv2 = None

CAPTURE_RATIO_FAIL = 0.15  # 저장시간/벽시계시간 비율이 이 미만이면 캡처 붕괴로 판정


def mp4_frame_count(path: Path) -> int | None:
    if cv2 is None:
        return None
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return None
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return n if n > 0 else None


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("root", type=Path, help="데이터셋 루트 (meta/ data/ videos/ 포함 폴더)")
    args = p.parse_args()
    root = args.root.expanduser()

    info_path = root / "meta" / "info.json"
    if not info_path.exists():
        print(f"FAIL: {info_path} 없음 — LeRobotDataset 루트가 아님", file=sys.stderr)
        return 1
    info = json.loads(info_path.read_text())
    fps = info["fps"]
    chunks_size = info.get("chunks_size", 1000)
    video_keys = [k for k, v in info["features"].items() if v.get("dtype") == "video"]

    episodes = []
    with open(root / "meta" / "episodes.jsonl") as f:
        for line in f:
            episodes.append(json.loads(line))
    if not episodes:
        print("FAIL: 에피소드가 없음", file=sys.stderr)
        return 1
    if len(episodes) != info.get("total_episodes"):
        print(f"WARN: episodes.jsonl {len(episodes)}개 != info.json total_episodes {info.get('total_episodes')}")

    print(f"데이터셋: {root}")
    print(f"에피소드 {len(episodes)}개, 명목 {fps}fps, 카메라 {len(video_keys)}개\n")

    any_fail = False
    prev_mtime = None
    for ep in episodes:
        idx = ep["episode_index"]
        length = ep["length"]
        chunk = idx // chunks_size
        problems, warns = [], []

        # 1·2. 파일 존재 + 프레임 수 일치
        pq_path = root / info["data_path"].format(episode_chunk=chunk, episode_index=idx)
        rows = None
        if not pq_path.exists():
            problems.append("parquet 없음")
        else:
            rows = pq.read_table(pq_path).num_rows
            if rows != length:
                problems.append(f"parquet {rows}행 != 메타 length {length}")

        ep_mtime = None
        for key in video_keys:
            v_path = root / info["video_path"].format(episode_chunk=chunk, video_key=key, episode_index=idx)
            if not v_path.exists():
                problems.append(f"{key} mp4 없음")
                continue
            ep_mtime = max(ep_mtime or 0.0, v_path.stat().st_mtime)
            n = mp4_frame_count(v_path)
            if n is None:
                warns.append(f"{key} 프레임 수 확인 불가(코덱/OpenCV)")
            elif n != length:
                problems.append(f"{key} mp4 {n}프레임 != 메타 length {length}")

        # 3. 값 건전성
        if rows:
            table = pq.read_table(pq_path, columns=["action", "observation.state"])
            for col in ("action", "observation.state"):
                arr = np.array(table[col].to_pylist(), dtype=np.float64)
                if np.isnan(arr).any():
                    problems.append(f"{col}에 NaN")
                elif length > 5 and np.allclose(arr.std(axis=0), 0):
                    warns.append(f"{col} 전 구간 상수 — 멈춘 센서/통신 의심")

        # 4. 캡처율 추정 (mtime 간격 대조 — 첫 에피소드는 기준이 없어 스킵)
        if ep_mtime is not None and prev_mtime is not None:
            wall_gap = ep_mtime - prev_mtime
            captured = length / fps
            if wall_gap > 0:
                ratio = captured / wall_gap
                if ratio < CAPTURE_RATIO_FAIL:
                    problems.append(
                        f"캡처 붕괴 의심: 저장 {captured:.1f}s vs 벽시계 ≤{wall_gap:.0f}s "
                        f"(비율 {ratio:.2f} < {CAPTURE_RATIO_FAIL})")
        if ep_mtime is not None:
            prev_mtime = ep_mtime

        status = "FAIL" if problems else ("WARN" if warns else "PASS")
        any_fail |= bool(problems)
        detail = "; ".join(problems + warns)
        print(f"  ep{idx:03d} [{status}] {length:4d} frames ({length / fps:5.1f}s)"
              + (f" — {detail}" if detail else ""))

    print()
    if any_fail:
        print("판정: FAIL — 위 에피소드는 재녹화를 권장. (파일은 옮기지 말 것 — 메타가 깨짐. "
              "에피소드 삭제가 필요하면 lerobot 데이터셋 도구를 사용하거나 태스크 전체 재수집)")
        return 1
    print("판정: PASS — 학습 파이프라인에 사용 가능")
    return 0


if __name__ == "__main__":
    sys.exit(main())
