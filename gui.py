import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import cv2
from PIL import Image, ImageTk
import os
import glob
import threading
import sys
import time

# 导入功能模块
from camera import VideoStream
from calibration import CameraCalibrator
# 导入新扫描模块
from scanner import DeviceScanner


# --- 1. 日志重定向类 (用于将 print 输出到 GUI) ---
class TextRedirector(object):
    def __init__(self, widget, tag="stdout"):
        self.widget = widget
        self.tag = tag

    def write(self, str):
        # 使用 after 方法确保在主线程更新 UI，防止多线程崩溃
        self.widget.after(0, self._append, str)

    def _append(self, str):
        try:
            self.widget.configure(state='normal')
            self.widget.insert(tk.END, str, (self.tag,))
            self.widget.see(tk.END)  # 自动滚动到底部
            self.widget.configure(state='disabled')
        except:
            pass

    def flush(self):
        pass


# --------------------------------------------------

class CameraGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("IP摄像头标定工具 (IP Camera Calibration Tool)")
        self.root.geometry("1600x850")

        # --- 状态变量 ---
        self.vs = None
        self.calibrator = None
        self.is_rectifying = False
        self.save_dir = "./chess"
        self.device_list = []

        if not os.path.exists(self.save_dir):
            os.makedirs(self.save_dir)

        self.snapshot_count = self._get_next_index()

        # --- 布局 ---
        # 左侧控制面板
        self.control_panel = tk.Frame(root, width=350, bg="#f0f0f0")
        self.control_panel.pack(side=tk.LEFT, fill=tk.BOTH, padx=10, pady=10)  # fill=BOTH 让它占满左边垂直空间

        # 右侧视频显示
        self.video_panel = tk.Label(root, text="视频未启动", bg="black", fg="white")
        self.video_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self._init_controls()

    def _get_next_index(self):
        files = glob.glob(os.path.join(self.save_dir, "chess_*.jpg"))
        max_idx = -1
        for f in files:
            try:
                name = os.path.basename(f)
                part = name.replace("chess_", "").replace(".jpg", "")
                if part.isdigit():
                    idx = int(part)
                    if idx > max_idx:
                        max_idx = idx
            except:
                continue
        return max_idx + 1

    def _init_controls(self):
        # 1. 连接设置
        p1 = ttk.LabelFrame(self.control_panel, text="相机连接与发现")
        p1.pack(fill=tk.X, pady=5)

        # ONVIF 账号密码
        f_auth = tk.Frame(p1)
        f_auth.pack(fill=tk.X, padx=5, pady=2)
        ttk.Label(f_auth, text="ONVIF账号:").pack(side=tk.LEFT)
        self.entry_user = ttk.Entry(f_auth, width=10)
        self.entry_user.insert(0, "admin")
        self.entry_user.pack(side=tk.LEFT, padx=5)

        ttk.Label(f_auth, text="密码:").pack(side=tk.LEFT)
        self.entry_pass = ttk.Entry(f_auth, width=10, show="*")
        self.entry_pass.insert(0, "123456")
        self.entry_pass.pack(side=tk.LEFT, padx=5)

        self.btn_scan = ttk.Button(p1, text="扫描局域网/USB设备", command=self.start_scan)
        self.btn_scan.pack(fill=tk.X, padx=5, pady=5)

        ttk.Label(p1, text="选择或输入 RTSP / ID:").pack(anchor=tk.W, padx=5)
        self.combo_url = ttk.Combobox(p1)
        self.combo_url.pack(fill=tk.X, padx=5, pady=2)
        self.combo_url['values'] = ["0"]
        self.combo_url.current(0)

        ttk.Label(p1, text="分辨率 (宽x高):").pack(anchor=tk.W, padx=5)
        self.entry_res = ttk.Entry(p1)
        self.entry_res.insert(0, "1920x1080")
        self.entry_res.pack(fill=tk.X, padx=5, pady=5)

        self.btn_connect = ttk.Button(p1, text="开始推流", command=self.toggle_stream)
        self.btn_connect.pack(fill=tk.X, padx=5, pady=5)

        # 2. 采集图像
        p2 = ttk.LabelFrame(self.control_panel, text="数据采集")
        p2.pack(fill=tk.X, pady=5)

        self.lbl_count = ttk.Label(p2, text=f"下一张: chess_{self.snapshot_count:02d}.jpg")
        self.lbl_count.pack(pady=5)

        self.btn_snap = ttk.Button(p2, text="截图保存", command=self.take_snapshot)
        self.btn_snap.pack(fill=tk.X, padx=5, pady=5)

        # 3. 标定设置
        p3 = ttk.LabelFrame(self.control_panel, text="标定操作")
        p3.pack(fill=tk.X, pady=5)

        ttk.Label(p3, text="角点数 (宽x高):").pack(anchor=tk.W, padx=5)
        self.entry_corners = ttk.Entry(p3)
        self.entry_corners.insert(0, "8x6")  # 注意：修改这里以匹配你的棋盘格
        self.entry_corners.pack(fill=tk.X, padx=5)

        ttk.Label(p3, text="方格尺寸 (mm):").pack(anchor=tk.W, padx=5)
        self.entry_square = ttk.Entry(p3)
        self.entry_square.insert(0, "20")
        self.entry_square.pack(fill=tk.X, padx=5, pady=5)

        self.btn_calib = ttk.Button(p3, text="开始标定计算", command=self.run_calibration)
        self.btn_calib.pack(fill=tk.X, padx=5, pady=5)

        self.btn_load = ttk.Button(p3, text="加载参数文件", command=self.load_calibration)
        self.btn_load.pack(fill=tk.X, padx=5, pady=5)

        # 4. 矫正预览
        p4 = ttk.LabelFrame(self.control_panel, text="畸变矫正")
        p4.pack(fill=tk.X, pady=5)

        self.var_rectify = tk.BooleanVar()
        self.chk_rectify = ttk.Checkbutton(p4, text="启用矫正预览", variable=self.var_rectify,
                                           command=self.toggle_rectify)
        self.chk_rectify.pack(pady=10)

        # --- 5. 运行日志 (新增部分，填补左下角空白) ---
        p5 = ttk.LabelFrame(self.control_panel, text="运行日志")
        # expand=True, fill=tk.BOTH 让它自动撑满剩下的垂直空间
        p5.pack(fill=tk.BOTH, expand=True, pady=5)

        # 创建滚动文本框
        self.log_text = scrolledtext.ScrolledText(p5, height=5, state='disabled', font=("Consolas", 9))
        self.log_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

        # 配置标签颜色
        self.log_text.tag_config("stdout", foreground="black")
        self.log_text.tag_config("stderr", foreground="red")  # 错误显示红色

        # 重定向 sys.stdout 和 sys.stderr
        sys.stdout = TextRedirector(self.log_text, "stdout")
        sys.stderr = TextRedirector(self.log_text, "stderr")

        print("系统就绪。日志已重定向至此窗口...")

    # --- 逻辑功能区 ---

    def start_scan(self):
        user = self.entry_user.get()
        pwd = self.entry_pass.get()

        self.btn_scan.config(state=tk.DISABLED, text="扫描中...")
        self.combo_url.set("正在扫描...")
        self.root.update()

        print(f"正在启动扫描线程 (User: {user})...")  # 这行字现在会显示在左下角

        scanner = DeviceScanner(user, pwd, self.on_scan_finished)
        scanner.start()

    def on_scan_finished(self, devices):
        self.root.after_idle(lambda: self._update_combo(devices))

    def _update_combo(self, devices):
        self.device_list = devices
        labels = [d['label'] for d in devices]
        if not labels:
            labels = ["未发现设备"]
            print("扫描结束: 未发现设备")
        else:
            print(f"扫描结束: 发现 {len(devices)} 个设备")

        self.combo_url['values'] = labels
        self.combo_url.current(0)
        self.btn_scan.config(state=tk.NORMAL, text="扫描局域网/USB设备")

    def toggle_stream(self):
        if self.vs is not None:
            print("正在停止推流...")
            self.vs.stop()
            self.vs = None
            self.btn_connect.config(text="开始推流", state=tk.NORMAL)
            self.video_panel.config(image='', text="视频停止")
            return

        try:
            w, h = map(int, self.entry_res.get().lower().split('x'))
            self.calibrator = CameraCalibrator((w, h))
        except:
            messagebox.showerror("错误", "分辨率格式无效")
            return

        selection = self.combo_url.get()
        url_to_use = selection
        for d in self.device_list:
            if d['label'] == selection:
                url_to_use = d['value']
                break

        print(f"准备连接: {url_to_use}")
        self.btn_connect.config(text="正在连接...", state=tk.DISABLED)

        def connect_thread():
            try:
                # 尝试连接，VideoStream start 方法现在会返回 self
                new_vs = VideoStream(url_to_use).start()
                # 简单检查是否真的打开了 (可选)
                time.sleep(1)
                if new_vs.cap.isOpened():
                    print("连接成功！")
                    self.root.after_idle(lambda: self._on_stream_started(new_vs))
                else:
                    print("连接失败: 无法打开视频源")
                    new_vs.stop()
                    self.root.after_idle(lambda: self._on_stream_failed())
            except Exception as e:
                print(f"连接异常: {e}")
                self.root.after_idle(lambda: self._on_stream_failed())

        threading.Thread(target=connect_thread, daemon=True).start()

    def _on_stream_started(self, new_vs):
        self.vs = new_vs
        self.btn_connect.config(text="停止推流", state=tk.NORMAL)
        self.update_video_loop()

    def _on_stream_failed(self):
        self.btn_connect.config(text="开始推流", state=tk.NORMAL)
        messagebox.showerror("错误", "无法连接到相机，请检查网络或地址。")

    def update_video_loop(self):
        if self.vs is None:
            return

        ret, frame = self.vs.read()
        if ret and frame is not None:
            display_frame = frame

            if self.var_rectify.get() and self.calibrator.is_calibrated:
                rectified = self.calibrator.rectify_image(frame)
                try:
                    display_frame = cv2.vconcat([frame, rectified])
                    h = frame.shape[0]
                    cv2.line(display_frame, (0, h), (frame.shape[1], h), (0, 255, 0), 2)
                    cv2.putText(display_frame, "Original", (30, 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
                    cv2.putText(display_frame, "Rectified", (30, h + 60),
                                cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3)
                except:
                    display_frame = rectified

            # 显示
            try:
                cv_image = cv2.cvtColor(display_frame, cv2.COLOR_BGR2RGB)
                panel_w = self.video_panel.winfo_width()
                panel_h = self.video_panel.winfo_height()

                if panel_w > 10 and panel_h > 10:
                    pil_image = Image.fromarray(cv_image)
                    img_w, img_h = pil_image.size
                    ratio = min(panel_w / img_w, panel_h / img_h)
                    new_size = (int(img_w * ratio), int(img_h * ratio))

                    pil_image = pil_image.resize(new_size, Image.Resampling.LANCZOS)
                    imgtk = ImageTk.PhotoImage(image=pil_image)

                    self.video_panel.imgtk = imgtk
                    self.video_panel.config(image=imgtk, text="")
            except Exception as e:
                print(f"显示错误: {e}")

        self.root.after(30, self.update_video_loop)

    def take_snapshot(self):
        if self.vs is None:
            messagebox.showwarning("提示", "请先启动视频推流")
            return
        ret, frame = self.vs.read()
        if ret and frame is not None:
            file_name = f"chess_{self.snapshot_count:02d}.jpg"
            save_path = os.path.join(self.save_dir, file_name)
            cv2.imwrite(save_path, frame)

            print(f"已保存截图: {file_name}")  # 这也会显示在日志窗口

            self.snapshot_count += 1
            self.lbl_count.config(text=f"下一张: chess_{self.snapshot_count:02d}.jpg")

    def run_calibration(self):
        if self.calibrator is None:
            messagebox.showerror("错误", "请先启动视频流以初始化图像尺寸。")
            return

        try:
            corner_str = self.entry_corners.get()
            w, h = map(int, corner_str.lower().split('x'))
            square = int(self.entry_square.get())
        except:
            messagebox.showerror("错误", "标定参数无效")
            return

        self.root.config(cursor="wait")
        self.btn_calib.config(state=tk.DISABLED, text="正在计算中...")
        print("--- 开始标定计算，请耐心等待 ---")

        threading.Thread(target=self._calibration_thread_worker, args=(w, h, square), daemon=True).start()

    def _calibration_thread_worker(self, w, h, square):
        # 这里的 print 输出会实时显示在日志窗口
        success = self.calibrator.calibration(corner_height=h, corner_width=w, square_size=square,
                                              image_dir=self.save_dir)
        self.root.after_idle(lambda: self._on_calibration_finished(success))

    def _on_calibration_finished(self, success):
        self.root.config(cursor="")
        self.btn_calib.config(state=tk.NORMAL, text="开始标定计算")

        if success:
            self.calibrator.save_params()
            print(f"标定成功! RMS: {success}")
            messagebox.showinfo("成功", f"标定完成。\nRMS: {success}")
        else:
            print("标定失败。")
            messagebox.showerror("失败", "标定失败。\n请检查图片和角点设置。")

    def load_calibration(self):
        if self.calibrator is None:
            try:
                w, h = map(int, self.entry_res.get().lower().split('x'))
                self.calibrator = CameraCalibrator((w, h))
            except:
                messagebox.showerror("错误", "请检查分辨率")
                return
        file_path = filedialog.askopenfilename(filetypes=[("XML files", "*.xml")])
        if file_path:
            if self.calibrator.load_params(file_path):
                print(f"参数已加载: {file_path}")
                messagebox.showinfo("成功", "参数已加载")
            else:
                print("参数加载失败")
                messagebox.showerror("错误", "参数加载失败")

    def toggle_rectify(self):
        if self.var_rectify.get():
            if not self.calibrator or not self.calibrator.is_calibrated:
                print("警告: 尝试开启矫正但未找到参数")
                messagebox.showwarning("警告", "尚未进行标定或加载参数！")
                self.var_rectify.set(False)
            else:
                print("开启畸变矫正预览")
        else:
            print("关闭畸变矫正预览")


if __name__ == "__main__":
    root = tk.Tk()
    app = CameraGUI(root)
    root.mainloop()