import multiprocessing
import threading
import queue
import asyncio
import os
import logging
from pathlib import Path
from datetime import datetime
from time import monotonic

import numpy as np
import cv2


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

UDP_HOST = '0.0.0.0'
IMAGE_UDP_PORT = 8001
VIDEO_FPS = 30

image_count = 0

image_queue = multiprocessing.Queue(maxsize=10)
record_queue = queue.Queue()

current_folder = Path(__file__).resolve().parent
media_dir = os.path.join(current_folder, 'media')
os.makedirs(media_dir, exist_ok=True)
video_path = os.path.join(media_dir, datetime.now().strftime('%Y%m%d_%H%M%S') + '.mp4')


async def stats_printer():
    global image_count
    while True:
        await asyncio.sleep(1.0)
        logger.info(f'Image: {image_count} Hz')
        image_count = 0


def record_worker():
    writer = None
    prev_frame = None
    start_time = None
    written = 0
    while True:
        item = record_queue.get()
        if item is None:
            break
        recv_time, raw_data = item
        try:
            np_arr = np.frombuffer(raw_data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is None:
                continue
            if writer is None:
                height, width = frame.shape[:2]
                writer = cv2.VideoWriter(
                    video_path,
                    cv2.VideoWriter_fourcc(*'mp4v'),
                    VIDEO_FPS,
                    (width, height),
                )
                if not writer.isOpened():
                    raise RuntimeError(f"Cannot open MP4 writer: {video_path}")
                start_time = recv_time
                logger.info(f'Recording to {video_path} ({width}x{height} @ {VIDEO_FPS}fps)')

            # 실제 경과 시간에 해당하는 타임라인 위치까지 프레임을 채운다.
            # 수신이 느리면 이전 프레임으로 빈 구간을 메우고,
            # 수신이 VIDEO_FPS보다 빠르면 초과분은 건너뛴다.
            target = int((recv_time - start_time) * VIDEO_FPS) + 1
            while written < target - 1 and prev_frame is not None:
                writer.write(prev_frame)
                written += 1
            if written < target:
                writer.write(frame)
                written += 1
            prev_frame = frame
        except Exception as e:
            logger.error(f'Video write error: {e}')
    if writer is not None:
        writer.release()
        logger.info(f'Video saved: {video_path} ({written / VIDEO_FPS:.1f}s)')


def display_worker(q):
    while True:
        try:
            image_data = q.get()
            if image_data is None:
                break

            np_arr = np.frombuffer(image_data, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if image is not None:
                cv2.imshow('Real-time Stream', image)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break
        except:
            pass
    cv2.destroyAllWindows()


class ImageUdpServerProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport):
        logger.info(f'Image server started on port {IMAGE_UDP_PORT}')

    def datagram_received(self, data, addr):
        global image_count
        try:
            image_count += 1
            record_queue.put((monotonic(), data))
            if not image_queue.full():
                image_queue.put_nowait(data)
        except Exception as e:
            logger.error(f'Image UDP error: {e}')

    def connection_lost(self, exc):
        pass


async def main():
    loop = asyncio.get_running_loop()

    image_transport, _ = await loop.create_datagram_endpoint(
        lambda: ImageUdpServerProtocol(),
        local_addr=(UDP_HOST, IMAGE_UDP_PORT)
    )

    display_proc = multiprocessing.Process(target=display_worker, args=(image_queue, ))
    display_proc.start()

    record_thread = threading.Thread(target=record_worker, daemon=True)
    record_thread.start()

    stats_task = asyncio.create_task(stats_printer())

    try:
        logger.info('Servers are running. Press Ctrl+C to stop.')
        while True:
            await asyncio.sleep(3600.0)
    except asyncio.CancelledError:
        pass
    finally:
        stats_task.cancel()
        try:
            await stats_task
        except asyncio.CancelledError:
            pass

        image_transport.close()

        record_queue.put(None)
        record_thread.join()

        try:
            image_queue.put_nowait(None)
        except queue.Full:
            pass

        display_proc.join(timeout=5)
        if display_proc.is_alive():
            display_proc.terminate()
            display_proc.join()

        image_queue.cancel_join_thread()
        image_queue.close()


if __name__ == '__main__':
    multiprocessing.freeze_support()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Shutting down...")
    finally:
        logger.info("Shutdown complete.")
