import json
import logging
import os
import queue
import tkinter as tk
from tkinter import filedialog, ttk

from ModbusTcpServer import ModbusTcpServer

logger = logging.getLogger("SimTest")

# Modbus TCP 服务默认地址（端口 5020 避免与系统 502 冲突，后续可由配置文件覆盖）
SERVER_HOST = "0.0.0.0"
SERVER_PORT = 5020

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


# 从站1 输出通道默认配置：机箱编号固定为 2
OUTPUT_CHASSIS = 2
# (板卡型号, 槽位号, 起始通道号, 结束通道号)
OUTPUT_BOARDS = [
    ("NI-9403-DO", 3, 1, 32),
    ("NI-9476-DO", 4, 1, 32),
    ("NI-9266-AO", 7, 1, 16),
    ("NI-9266-AO", 8, 1, 16),
]


def build_output_channel_rows():
    """生成从站1 输出通道行数据，输出值默认为 0。"""
    rows = []
    idx = 1
    for model, slot, start_ch, end_ch in OUTPUT_BOARDS:
        for channel in range(start_ch, end_ch + 1):
            rows.append([idx, OUTPUT_CHASSIS, model, slot, channel, 0])
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

    def __init__(self, parent, headers, col_widths, editable_columns=()):
        super().__init__(parent)
        self.headers = headers
        self.col_widths = list(col_widths)
        self.editable_columns = set(editable_columns)
        self.rows = []
        self._edit_entry = None
        self._edit_row = None
        self._edit_col = None

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
        self.body_canvas.bind("<Button-1>", self._on_body_click)

    def set_rows(self, rows):
        self.rows = [list(r) for r in rows]
        self._draw_body()

    def update_last_column(self, values):
        """用 values 更新每行最后一列（当前值/输出值）并重绘。"""
        for i, val in enumerate(values):
            if i < len(self.rows):
                self.rows[i][-1] = val
        self._render_body()

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
        self._finish_edit()
        self._render_body()

    def _render_body(self):
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

    # ---- 可编辑单元格 ----
    def _on_body_click(self, event):
        x = self.body_canvas.canvasx(event.x)
        y = self.body_canvas.canvasy(event.y)
        col = self._col_at(x)
        row = self._row_at(y)
        if row is None or col is None or col not in self.editable_columns:
            if self._edit_entry is not None:
                self._finish_edit()
            return
        self._start_edit(row, col)

    def _col_at(self, x):
        w = self.body_canvas.winfo_width()
        xs = self._col_x(w)
        for j in range(len(self.headers)):
            x0 = xs[j]
            x1 = xs[j + 1] if j + 1 < len(xs) else w
            if x0 <= x < x1:
                return j
        return None

    def _row_at(self, y):
        row = int(y // self.ROW_H)
        if 0 <= row < len(self.rows):
            return row
        return None

    def _start_edit(self, row, col):
        self._finish_edit()
        w = self.body_canvas.winfo_width()
        xs = self._col_x(w)
        x0 = xs[col]
        x1 = xs[col + 1] if col + 1 < len(xs) else w
        y0 = row * self.ROW_H
        y1 = y0 + self.ROW_H

        entry = tk.Entry(self.body_canvas, justify="center", relief="solid", bd=1,
                         font=self.FONT)
        entry.insert(0, str(self.rows[row][col]))
        self._edit_entry = entry
        self._edit_row = row
        self._edit_col = col
        self.body_canvas.create_window(x0, y0, window=entry, anchor="nw",
                                       width=x1 - x0, height=y1 - y0)
        entry.bind("<Return>", lambda e: self._finish_edit())
        entry.bind("<FocusOut>", lambda e: self._finish_edit())
        entry.focus_set()
        entry.select_range(0, "end")

    def _finish_edit(self):
        entry = self._edit_entry
        if entry is None:
            return
        val = entry.get()
        row, col = self._edit_row, self._edit_col
        self._edit_entry = None
        self._edit_row = None
        self._edit_col = None
        entry.destroy()
        if row is not None and 0 <= row < len(self.rows) and 0 <= col < len(self.rows[row]):
            self.rows[row][col] = val
        self._render_body()


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
        self.config = None
        self.slaves = []
        self.modbus_server = None

        self.log_queue = queue.Queue()
        self.data_queue = queue.Queue()
        self._setup_logging()
        self._build_ui()

        # 默认填充从站1 输入/输出通道
        self.update_input_channels(build_input_channel_rows())
        self.update_output_channels(build_output_channel_rows())

        self.after(100, self._poll_log_queue)
        self.after(100, self._poll_data_queue)
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

    def _poll_data_queue(self):
        latest = None
        try:
            while True:
                latest = self.data_queue.get_nowait()
        except queue.Empty:
            pass
        if latest is not None:
            self._apply_input_values(latest)
        self.after(100, self._poll_data_queue)

    def _apply_input_values(self, values):
        """用接收到的数据刷新输入通道当前值。"""
        self.input_table.update_last_column(values)

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
        self.output_table = self._build_channel_block(slave1, "输出通道", OUTPUT_HEADERS, 1,
                                                      editable_columns=(5,))

        # 从站2/3/4：空白页
        for name in ("从站2", "从站3", "从站4"):
            notebook.add(ttk.Frame(notebook), text=name)

    def _build_channel_block(self, parent, title, headers, column, editable_columns=()):
        block = tk.LabelFrame(parent, text=title, bd=2)
        block.grid(row=0, column=column, sticky="nsew", padx=2, pady=2)
        block.rowconfigure(0, weight=1)
        block.columnconfigure(0, weight=1)

        table = ChannelTable(block, headers,
                             [HEADER_WIDTHS.get(h, 110) for h in headers],
                             editable_columns)
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
        """解析配置文件（JSON），加载从站 ip/port 配置。"""
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.config = json.load(f)
            self.slaves = self.config.get("slaves", [])
            logger.info("配置文件已加载: %s，从站数量: %d", path, len(self.slaves))
            for i, slave in enumerate(self.slaves, 1):
                logger.info("从站%d: %s:%s", i, slave.get("ip"), slave.get("port"))
        except Exception as exc:
            logger.error("配置文件加载失败: %s", exc)
            self.slaves = []

    # ------------------------------------------------------------------ #
    # 参数配置 —— 启动/停止服务
    # ------------------------------------------------------------------ #
    def _toggle_server(self):
        if self.server_running:
            self.stop_server()
        else:
            self.start_server()

    def start_server(self):
        """启动 Modbus TCP server。"""
        if self.server_running:
            return
        self.modbus_server = ModbusTcpServer(
            host=SERVER_HOST,
            port=SERVER_PORT,
            on_data_received=self._on_data_received,
            on_data_sent=self._on_data_sent,
            on_write_registers=self._on_write_registers,
            on_read_holding_registers=self._on_read_holding_registers,
        )
        if self.modbus_server.start():
            self.server_running = True
            self.server_btn.config(text="停止服务")

    def stop_server(self):
        """停止 Modbus TCP server。"""
        if not self.server_running:
            return
        if self.modbus_server:
            self.modbus_server.stop()
        self.server_running = False
        self.server_btn.config(text="启动服务")

    def _on_data_received(self, data, client_host):
        """收到 client 数据回调，依据来源 IP 判断从站。"""
        slave = self._find_slave(client_host)
        if slave is not None:
            logger.info("从站%d (%s) 收到数据: %s", slave, client_host, data.hex())
        else:
            logger.info("收到数据(未知来源 %s): %s", client_host, data.hex())

    def _on_data_sent(self, data):
        """向 client 发送数据回调。"""
        logger.info("发送数据: %s", data.hex())

    def _on_write_registers(self, client_host, address, registers):
        """client 写入多个保持寄存器，依据 IP 更新从站1 输入通道当前值。

        数据为 72 字节：前 64 个 DI 通道按位打包（8 通道/字节），
        后 32 个 AI 通道各占 2 字节（16 位大端）。
        """
        slave1_ip = self.slaves[0]["ip"] if self.slaves else None
        if slave1_ip is None or client_host != slave1_ip:
            return
        data = b"".join(r.to_bytes(2, "big") for r in registers)
        values = self._parse_input_bytes(data)
        self.data_queue.put(values)

    def _on_read_holding_registers(self, client_host, address, count):
        """client 读保持寄存器，依据 IP 返回从站1 输出通道打包值。"""
        slave1_ip = self.slaves[0]["ip"] if self.slaves else None
        if slave1_ip is None or client_host != slave1_ip:
            return None
        full = self._pack_output_registers()  # 36 个寄存器 = 72 字节
        return full[address:address + count]

    def _pack_output_registers(self):
        """把 96 个输出通道打包成 36 个寄存器（72 字节）。

        前 64 个 DO 通道按位打包（8 通道/字节，共 8 字节 = 4 寄存器），
        后 32 个 AO 通道各占 2 字节（16 位大端，共 64 字节 = 32 寄存器）。
        """
        buf = bytearray(72)
        for i in range(64):
            if self._to_bit(self.output_table.rows[i][-1]):
                buf[i // 8] |= 1 << (i % 8)
        for k in range(32):
            val = self._to_int(self.output_table.rows[64 + k][-1])
            buf[8 + 2 * k] = (val >> 8) & 0xFF
            buf[8 + 2 * k + 1] = val & 0xFF
        return [int.from_bytes(buf[i:i + 2], "big") for i in range(0, 72, 2)]

    @staticmethod
    def _parse_input_bytes(data):
        """把 72 字节解析成 96 个通道值（index i = 通道 i+1）。"""
        values = []
        for i in range(8):
            byte = data[i] if i < len(data) else 0
            for j in range(8):
                values.append((byte >> j) & 1)
        for k in range(32):
            base = 8 + 2 * k
            hi = data[base] if base < len(data) else 0
            lo = data[base + 1] if base + 1 < len(data) else 0
            values.append((hi << 8) | lo)
        return values

    @staticmethod
    def _to_bit(val):
        """把值解释成 0/1。"""
        try:
            return 1 if int(val) else 0
        except (ValueError, TypeError):
            return 0

    @staticmethod
    def _to_int(val):
        """把值解释成整数。"""
        try:
            return int(val)
        except (ValueError, TypeError):
            return 0

    def _find_slave(self, client_host):
        """根据来源 IP 匹配从站编号（1 起），未匹配返回 None。"""
        for i, slave in enumerate(self.slaves, 1):
            if slave.get("ip") == client_host:
                return i
        return None

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
