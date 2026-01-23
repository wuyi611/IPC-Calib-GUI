import cv2
import threading
import socket
import time
from urllib.parse import urlparse

# --- 增强的容错导入 ---
try:
    import netifaces
    from onvif import ONVIFCamera
    from wsdiscovery import WSDiscovery, Scope

    SCAN_DEPENDENCIES_OK = True
except ImportError as e:
    print(f"警告: 缺少扫描所需的库 ({e})，局域网扫描功能将不可用。")
    print("请运行: pip install onvif-zeep netifaces WSDiscovery")
    SCAN_DEPENDENCIES_OK = False


# --------------------

class DeviceScanner(threading.Thread):
    def __init__(self, onvif_user, onvif_pass, callback):
        super().__init__()
        self.onvif_user = onvif_user
        self.onvif_pass = onvif_pass
        self.callback = callback
        self.daemon = True
        self.found_devices = []

    def run(self):
        print("--- 开始设备扫描 ---")

        # 1. 扫描本地 USB 相机
        self.scan_usb_cameras()

        # 2. 扫描 ONVIF 网络相机
        if SCAN_DEPENDENCIES_OK:
            self.scan_onvif_cameras()
        else:
            self.found_devices.append({"label": "[错误] 缺少扫描库", "value": "0"})

        # 3. 完成
        if self.callback:
            self.callback(self.found_devices)
        print("--- 扫描结束 ---")

    def scan_usb_cameras(self):
        # 简单扫描前10个索引
        for i in range(10):
            try:
                # 尝试打开相机
                cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(i)

                if cap.isOpened():
                    ret, _ = cap.read()
                    if ret:
                        # 本地相机显示格式
                        label = f"[本地USB] Camera ID: {i}"
                        self.found_devices.append({"label": label, "value": str(i)})
                    cap.release()
            except:
                pass

    def scan_onvif_cameras(self):
        if not SCAN_DEPENDENCIES_OK: return

        try:
            wsd = WSDiscovery()
            wsd.start()

            print("发送 ONVIF 探测包...")
            services = wsd.searchServices()

            unique_ips = set()

            for service in services:
                try:
                    ip = urlparse(service.getXAddrs()[0]).hostname
                    port = urlparse(service.getXAddrs()[0]).port
                    if not port: port = 80

                    if ip in unique_ips:
                        continue
                    unique_ips.add(ip)

                    print(f"发现 ONVIF 设备: {ip}:{port}，尝试获取流地址...")
                    self.get_stream_uri(ip, port)

                except Exception as e:
                    print(f"解析服务出错: {e}")

            wsd.stop()
        except Exception as e:
            print(f"ONVIF 扫描过程出错: {e}")

    def get_stream_uri(self, ip, port):
        try:
            mycam = ONVIFCamera(ip, port, self.onvif_user, self.onvif_pass)
            media = mycam.create_media_service()
            profiles = media.GetProfiles()

            # 遍历所有码流配置文件 (MainStream, SubStream等)
            for profile in profiles:
                stream_setup = {
                    'Stream': 'RTP-Unicast',
                    'Transport': {'Protocol': 'RTSP'}
                }
                res = media.GetStreamUri({'ProfileToken': profile.token, 'StreamSetup': stream_setup})

                rtsp_url = res.Uri

                # 自动注入账号密码 (用于连接，不用于显示)
                if self.onvif_user and self.onvif_pass and "@" not in rtsp_url:
                    parts = rtsp_url.split("://")
                    if len(parts) == 2:
                        rtsp_url = f"{parts[0]}://{self.onvif_user}:{self.onvif_pass}@{parts[1]}"

                # --- 修改处：只显示 [码流名] IP ---
                # 例如: [MainStream] 192.168.1.88
                label = f"[{profile.Name}] {ip}"

                # value 必须是 rtsp_url，否则无法连接
                self.found_devices.append({"label": label, "value": rtsp_url})
                print(f"  -> {label}")

        except Exception as e:
            print(f"  -> 无法连接 {ip}: {e}")