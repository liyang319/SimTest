import logging
import os
import queue
import tkinter as tk
from tkinter import filedialog, ttk

logger = logging.getLogger("SimTest")

# 输入/输出通道表头
INPUT_HEADERS = ("序号", "机箱编号", "板卡型号", "槽位号", "通道号", "当前值")
OUTPUT_HEADERS = ("序号", "机箱编号", "板卡型号", "槽位号", "通道号", "输出值")


class QueueLogHandler(logging.Handler):
    """将日志记录投递到队列，由 UI 线程统一刷新到“系统日志”区域（线程安全）。"""

    def __init__(self, log_queue):
        super().__init__()
        self.log_queue = log_queue

    def emit(self, record):
        try:
            self.log_queue.put(self.format(record))
        except Exception:
            pass


class SimTestApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SimTest模拟软件")
        self.geometry("1100x720")
        self.minsize(900, 600)

        self.server_running = False
        self.config_path = None

        self.log_queue = queue.Queue()
        self._setup_logging()
        self._build_ui()

        self.after(100, self._poll_log_queue)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        logger.info("程序启动")

    # ------------------------------------------------------------------ #
    # 日志
    # ------------------------------------------------------------------ #
    def _setup_logging(self):
        handler = QueueLogHandler(self.log_queue)
        handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s",
                                               "%H:%M:%S"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)

    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _append_log(self, msg):
        self.log_text.configure(state="normal")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=3)  # 从站设备 区域可拉伸
        self.rowconfigure(3, weight=1)  # 系统日志 区域可拉伸

        self._build_title()
        self._build_config_section()
        self._build_slave_section()
        self._build_log_section()

    def _build_title(self):
        title = tk.Label(self, text="SimTest模拟软件",
                         font=("Helvetica", 20, "bold"))
        title.grid(row=0, column=0, sticky="ew", pady=8)

    def _build_config_section(self):
        frame = tk.LabelFrame(self, text="参数配置", bd=2)
        frame.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 5))

        self.select_btn = ttk.Button(frame, text="配置文件",
                                     command=self._select_config_file)
        self.select_btn.pack(side="left", padx=(8, 4), pady=8)

        self.config_label = ttk.Label(frame, text="未选择配置文件")
        self.config_label.pack(side="left", padx=4, pady=8)

        self.server_btn = ttk.Button(frame, text="启动服务",
                                     command=self._toggle_server)
        self.server_btn.pack(side="left", padx=(24, 8), pady=8)

    def _build_slave_section(self):
        frame = tk.LabelFrame(self, text="从站设备", bd=2)
        frame.grid(row=2, column=0, sticky="nsew", padx=10, pady=5)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        notebook = ttk.Notebook(frame)
        notebook.grid(row=0, column=0, sticky="nsew", padx=5, pady=5)

        # 从站1：左右分栏（输入通道 / 输出通道）
        slave1 = ttk.Frame(notebook)
        notebook.add(slave1, text="从站1")
        slave1.rowconfigure(0, weight=1)
        slave1.columnconfigure(0, weight=1, uniform="slave1")
        slave1.columnconfigure(1, weight=1, uniform="slave1")

        self.input_tree = self._build_channel_block(slave1, "输入通道", INPUT_HEADERS, 0)
        self.output_tree = self._build_channel_block(slave1, "输出通道", OUTPUT_HEADERS, 1)

        # 从站2/3/4：空白页
        for name in ("从站2", "从站3", "从站4"):
            notebook.add(ttk.Frame(notebook), text=name)

    def _build_channel_block(self, parent, title, headers, column):
        block = tk.LabelFrame(parent, text=title, bd=2)
        block.grid(row=0, column=column, sticky="nsew", padx=5, pady=5)
        block.rowconfigure(0, weight=1)
        block.columnconfigure(0, weight=1)

        tree, vsb = self._make_channel_table(block, headers)
        tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        return tree

    def _make_channel_table(self, parent, headers):
        columns = [f"c{i}" for i in range(len(headers))]
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=15)
        for col, header in zip(columns, headers):
            tree.heading(col, text=header)
            width = 60 if header == "序号" else 110
            tree.column(col, width=width, anchor="center", stretch=True)

        vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        return tree, vsb

    def _build_log_section(self):
        frame = tk.LabelFrame(self, text="系统日志", bd=2)
        frame.grid(row=3, column=0, sticky="nsew", padx=10, pady=(5, 10))
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

        self.log_text = tk.Text(frame, state="disabled", wrap="word", height=10)
        vsb = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=vsb.set)
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=(5, 0), pady=5)
        vsb.grid(row=0, column=1, sticky="ns", padx=(0, 5), pady=5)

    # ------------------------------------------------------------------ #
    # 参数配置 —— 配置文件
    # ------------------------------------------------------------------ #
    def _select_config_file(self):
        path = filedialog.askopenfilename(
            title="选择配置文件",
            filetypes=[("JSON 文件", "*.json"), ("所有文件", "*.*")],
        )
        if not path:
            return
        self.config_path = path
        self.config_label.config(text=os.path.basename(path))
        self.load_config_file(path)

    def load_config_file(self, path):
        """预留接口：解析配置文件（JSON），后续实现。"""
        logger.info("配置文件已选择: %s（解析逻辑待实现）", path)

    # ------------------------------------------------------------------ #
    # 参数配置 —— 启动/停止服务
    # ------------------------------------------------------------------ #
    def _toggle_server(self):
        if self.server_running:
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        """预留接口：启动 Modbus TCP server，后续实现。"""
        self.server_running = True
        self.server_btn.config(text="停止服务")
        logger.info("服务已启动（待实现）")

    def stop_server(self):
        """预留接口：停止 Modbus TCP server，后续实现。"""
        self.server_running = False
        self.server_btn.config(text="启动服务")
        logger.info("服务已停止（待实现）")

    # ------------------------------------------------------------------ #
    # 从站通道表 —— 数据刷新（预留接口）
    # ------------------------------------------------------------------ #
    def update_input_channels(self, rows):
        """预留接口：刷新输入通道列表，rows 为通道数据列表。"""
        self._clear_tree(self.input_tree)
        for row in rows:
            self.input_tree.insert("", "end", values=row)

    def update_output_channels(self, rows):
        """预留接口：刷新输出通道列表，rows 为通道数据列表。"""
        self._clear_tree(self.output_tree)
        for row in rows:
            self.output_tree.insert("", "end", values=row)

    @staticmethod
    def _clear_tree(tree):
        for item in tree.get_children():
            tree.delete(item)

    # ------------------------------------------------------------------ #
    # 退出
    # ------------------------------------------------------------------ #
    def _on_close(self):
        if self.server_running:
            self.stop_server()
        self.destroy()


if __name__ == "__main__":
    app = SimTestApp()
    app.mainloop()
