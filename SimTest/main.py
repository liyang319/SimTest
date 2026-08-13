import logging
import os
import queue
import tkinter as tk
from tkinter import filedialog, ttk

logger = logging.getLogger("SimTest")

# 输入/输出通道表头
INPUT_HEADERS = ("序号", "机箱编号", "板卡型号", "槽位号", "通道号", "当前值")
OUTPUT_HEADERS = ("序号", "机箱编号", "板卡型号", "槽位号", "通道号", "输出值")

# 各列宽度，确保所有列标题无需横向滚动即可完整显示
HEADER_WIDTHS = {
    "序号": 45,
    "机箱编号": 80,
    "板卡型号": 110,
    "槽位号": 60,
    "通道号": 60,
    "当前值": 110,
    "输出值": 110,
}

# 从站1 输入通道默认配置：机箱编号固定为 2
INPUT_CHASSIS = 2
# (板卡型号, 槽位号, 起始通道号, 结束通道号)
INPUT_BOARDS = [
    ("NI-9403-DI", 1, 1, 32),
    ("NI-9426-DI", 2, 1, 31),
    ("NI-9427-DI", 2, 32, 32),
    ("NI-9203-AI", 5, 1, 16),
    ("NI-9203-AI", 6, 1, 16),
]


def build_input_channel_rows():
    """生成从站1 输入通道行数据，当前值默认为 0。"""
    rows = []
    idx = 1
    for model, slot, start_ch, end_ch in INPUT_BOARDS:
        for channel in range(start_ch, end_ch + 1):
            rows.append((idx, INPUT_CHASSIS, model, slot, channel, 0))
            idx += 1
    return rows


class ChannelTable(tk.Frame):
    """带单元格边框线的可滚动表格（固定表头 + 可滚动数据区）。"""

    HEADER_BG = "#e9e9e9"
    CELL_BG = "#ffffff"
    LINE = "#888888"
    ROW_H = 24
    HEADER_H = 26
    FONT = ("Helvetica", 12)
    HEADER_FONT = ("Helvetica", 12, "bold")

    def __init__(self, parent, headers, col_widths):
        super().__init__(parent)
        self.headers = headers
        self.col_widths = list(col_widths)
        self.rows = []

        self.header_canvas = tk.Canvas(self, height=self.HEADER_H, bg=self.HEADER_BG,
                                       highlightthickness=0, borderwidth=0)
        self.body_canvas = tk.Canvas(self, bg=self.CELL_BG,
                                     highlightthickness=0, borderwidth=0)
        vsb = ttk.Scrollbar(self, orient="vertical", command=self.body_canvas.yview)
        self.body_canvas.configure(yscrollcommand=vsb.set)

        self.header_canvas.grid(row=0, column=0, sticky="ew")
        self.body_canvas.grid(row=1, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, rowspan=2, sticky="ns")

        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)

        self.header_canvas.bind("<Configure>", self._draw_header)
        self.body_canvas.bind("<Configure>", self._draw_body)

    def set_rows(self, rows):
        self.rows = rows
        self._draw_body()

    def _col_x(self, width):
        total = sum(self.col_widths)
        xs = []
        x = 0.0
        for w in self.col_widths:
            xs.append(x)
            x += w * width / total
        return xs

    def _draw_header(self, event=None):
        c = self.header_canvas
        c.delete("all")
        w = c.winfo_width()
        if w <= 1:
            return
        xs = self._col_x(w)
        for j, header in enumerate(self.headers):
            x0 = xs[j]
            x1 = xs[j + 1] if j + 1 < len(xs) else w
            c.create_rectangle(x0, 0, x1, self.HEADER_H, fill=self.HEADER_BG, outline=self.LINE)
            c.create_text((x0 + x1) / 2, self.HEADER_H / 2, text=header,
                          anchor="center", font=self.HEADER_FONT)

    def _draw_body(self, event=None):
        c = self.body_canvas
        c.delete("all")
        w = c.winfo_width()
        if w <= 1:
            return
        xs = self._col_x(w)
        for i, row in enumerate(self.rows):
            y0 = i * self.ROW_H
            y1 = y0 + self.ROW_H
            for j, val in enumerate(row):
                x0 = xs[j]
                x1 = xs[j + 1] if j + 1 < len(xs) else w
                c.create_rectangle(x0, y0, x1, y1, fill=self.CELL_BG, outline=self.LINE)
                c.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=str(val),
                              anchor="center", font=self.FONT)
        c.configure(scrollregion=(0, 0, w, len(self.rows) * self.ROW_H))


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

        # 默认填充从站1 输入通道
        self.update_input_channels(build_input_channel_rows())

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

        style = ttk.Style(self)
        # 负左右 padding 抵消 macOS aqua 主题 Notebook 客户端区域自带的 9px 边框，
        # 上下保持默认，避免顶部的 tab 标签被内容区遮挡
        style.configure("TNotebook", padding=(-9, 0))

        notebook = ttk.Notebook(frame)
        notebook.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        # 从站1：左右分栏（输入通道 / 输出通道）
        slave1 = ttk.Frame(notebook)
        notebook.add(slave1, text="从站1")
        slave1.rowconfigure(0, weight=1)
        slave1.columnconfigure(0, weight=1, uniform="slave1")
        slave1.columnconfigure(1, weight=1, uniform="slave1")

        self.input_table = self._build_channel_block(slave1, "输入通道", INPUT_HEADERS, 0)
        self.output_table = self._build_channel_block(slave1, "输出通道", OUTPUT_HEADERS, 1)

        # 从站2/3/4：空白页
        for name in ("从站2", "从站3", "从站4"):
            notebook.add(ttk.Frame(notebook), text=name)

    def _build_channel_block(self, parent, title, headers, column):
        block = tk.LabelFrame(parent, text=title, bd=2)
        block.grid(row=0, column=column, sticky="nsew", padx=2, pady=2)
        block.rowconfigure(0, weight=1)
        block.columnconfigure(0, weight=1)

        table = ChannelTable(block, headers, [HEADER_WIDTHS.get(h, 110) for h in headers])
        table.grid(row=0, column=0, sticky="nsew")
        return table

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
        """刷新输入通道列表，rows 为通道数据列表。"""
        self.input_table.set_rows(rows)

    def update_output_channels(self, rows):
        """刷新输出通道列表，rows 为通道数据列表。"""
        self.output_table.set_rows(rows)

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
