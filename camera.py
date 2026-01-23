import cv2
import threading
import time
import os


class VideoStream:
    def __init__(self, url):
        # 优化 FFMPEG 参数
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;udp|fflags;nobuffer"
        # 兼容数字ID (本地摄像头) 和 字符串URL (RTSP)
        if str(url).isdigit():
            self.src = int(url)
        else:
            self.src = url

        self.cap = cv2.VideoCapture(self.src, cv2.CAP_FFMPEG)
        self.ret, self.frame = False, None
        self.stopped = False
        self.lock = threading.Lock()  # 添加锁保证线程安全

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