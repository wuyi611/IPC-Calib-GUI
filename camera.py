import cv2
import threading
import time
import os


class VideoStream:
    def __init__(self, url):
        # 兼容数字ID (本地摄像头) 和 字符串URL (RTSP)
        if str(url).isdigit():
            self.src = int(url)
        else:
            self.src = url

        self.ret, self.frame = False, None
        self.stopped = False
        self.lock = threading.Lock()  # 添加锁保证线程安全
        self.backend_name = "unknown"
        self.cap = self._open_capture()

    def _open_capture(self):
        if isinstance(self.src, int):
            return self._open_local_camera()
        return self._open_rtsp_stream()

    def _open_local_camera(self):
        backend_candidates = [("DirectShow", cv2.CAP_DSHOW)]

        msmf_backend = getattr(cv2, "CAP_MSMF", None)
        if msmf_backend is not None:
            backend_candidates.append(("Media Foundation", msmf_backend))

        backend_candidates.append(("Default", None))

        for backend_name, backend in backend_candidates:
            if backend is None:
                cap = cv2.VideoCapture(self.src)
            else:
                cap = cv2.VideoCapture(self.src, backend)

            if cap.isOpened():
                self.backend_name = backend_name
                return cap

            cap.release()

        self.backend_name = "Unavailable"
        return cv2.VideoCapture()

    def _open_rtsp_stream(self):
        # RTSP 流优先走 FFMPEG，失败后回退到默认后端。
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|fflags;nobuffer"

        cap = cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)
        if cap.isOpened():
            self.backend_name = "FFMPEG"
            return cap

        cap.release()
        cap = cv2.VideoCapture(self.src)
        if cap.isOpened():
            self.backend_name = "Default"
            return cap

        self.backend_name = "Unavailable"
        return cap

    def start(self):
        t = threading.Thread(target=self.update, args=())
        t.daemon = True
        t.start()
        return self

    def update(self):
        while not self.stopped:
            if not self.cap.isOpened():
                self.stop()
            else:
                ret, frame = self.cap.read()
                with self.lock:
                    self.ret = ret
                    self.frame = frame
            time.sleep(0.005)

    def read(self):
        with self.lock:
            return self.ret, self.frame

    def stop(self):
        self.stopped = True
        if self.cap.isOpened():
            self.cap.release()
