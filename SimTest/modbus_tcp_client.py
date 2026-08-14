"""Modbus TCP 客户端模拟器。

用于连接 SimTest 模拟软件的 Modbus TCP server，进行数据的读写测试。

用法：
    python modbus_tcp_client.py [--host 127.0.0.1] [--port 5020] [--device-id 1]

进入后输入 help 查看可用命令。
"""

import argparse
import sys
import time

from pymodbus.client import ModbusTcpClient

HELP = """可用命令：
  read_hr   <addr> [count]          读保持寄存器（对应输出通道/输出值）
  read_ir   <addr> [count]          读输入寄存器（对应模拟量输入/当前值）
  read_coils <addr> [count]         读线圈
  read_di   <addr> [count]          读离散输入
  read_out                          读从站1 输出通道打包值（36寄存器=72字节）
  read_out2                         读从站2 输出通道打包值（19寄存器=38字节）
  write_reg  <addr> <value>         写单个保持寄存器
  write_regs <addr> <v1> [v2 ...]   写多个保持寄存器
  write_coil <addr> <0|1>           写单个线圈
  write_coils <addr> <v1> [v2 ...]  写多个线圈
  loop [interval]                   循环发送 72 字节数据（DI 走位 + AI 递增）
  loop2 [interval]                  循环发送从站2 输入数据（48 DI + 8 AI，22字节）
  demo                              运行一次读写演示
  help                              显示本帮助
  quit / exit / q                   退出
"""


def make_trace():
    """构造收发数据回调，打印原始报文。"""

    def trace(sending, data):
        direction = "发送" if sending else "接收"
        print(f"  [{direction}] {data.hex(' ')}")
        return data

    return trace


def show_result(resp):
    """打印响应结果。"""
    if resp is None:
        print("  无响应（可能超时或连接断开）")
        return
    if resp.isError():
        print(f"  错误: {resp}")
        return
    bits = getattr(resp, "bits", None)
    if bits:
        print(f"  值: {bits}")
        return
    registers = getattr(resp, "registers", None)
    if registers:
        print(f"  值: {registers}")
        return
    print("  成功")


def parse_bool(text):
    """解析布尔值，支持 0/1/true/false。"""
    low = text.lower()
    if low in ("1", "true", "on", "yes"):
        return True
    if low in ("0", "false", "off", "no"):
        return False
    raise ValueError(f"无法解析布尔值: {text}")


def run_command(client, device_id, line):
    """执行一条命令，返回是否继续运行。"""
    parts = line.split()
    if not parts:
        return True
    cmd = parts[0].lower()

    if cmd in ("quit", "exit", "q"):
        return False
    if cmd in ("help", "h", "?"):
        print(HELP)
        return True
    if cmd == "demo":
        run_demo(client, device_id)
        return True
    if cmd in ("loop", "loop_send"):
        interval = float(parts[1]) if len(parts) > 1 else 0.2
        run_loop_send(client, device_id, interval)
        return True
    if cmd in ("loop2", "loop_slave2"):
        interval = float(parts[1]) if len(parts) > 1 else 0.2
        run_loop_send_slave2(client, device_id, interval)
        return True
    if cmd in ("read_out", "read_output"):
        run_read_output(client, device_id)
        return True
    if cmd in ("read_out2", "read_output2"):
        run_read_output_slave2(client, device_id)
        return True

    try:
        if cmd == "read_hr":
            addr = int(parts[1])
            count = int(parts[2]) if len(parts) > 2 else 1
            show_result(client.read_holding_registers(addr, count=count, device_id=device_id))
        elif cmd == "read_ir":
            addr = int(parts[1])
            count = int(parts[2]) if len(parts) > 2 else 1
            show_result(client.read_input_registers(addr, count=count, device_id=device_id))
        elif cmd == "read_coils":
            addr = int(parts[1])
            count = int(parts[2]) if len(parts) > 2 else 1
            show_result(client.read_coils(addr, count=count, device_id=device_id))
        elif cmd == "read_di":
            addr = int(parts[1])
            count = int(parts[2]) if len(parts) > 2 else 1
            show_result(client.read_discrete_inputs(addr, count=count, device_id=device_id))
        elif cmd == "write_reg":
            addr, value = int(parts[1]), int(parts[2])
            show_result(client.write_register(addr, value, device_id=device_id))
        elif cmd == "write_regs":
            addr = int(parts[1])
            values = [int(v) for v in parts[2:]]
            show_result(client.write_registers(addr, values, device_id=device_id))
        elif cmd == "write_coil":
            addr, value = int(parts[1]), parse_bool(parts[2])
            show_result(client.write_coil(addr, value, device_id=device_id))
        elif cmd == "write_coils":
            addr = int(parts[1])
            values = [parse_bool(v) for v in parts[2:]]
            show_result(client.write_coils(addr, values, device_id=device_id))
        else:
            print(f"  未知命令: {cmd}，输入 help 查看帮助")
    except (IndexError, ValueError) as exc:
        print(f"  参数错误: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"  执行失败: {exc}")
    return True


def run_loop_send(client, device_id, interval):
    """循环发送 72 字节数据（DI 走位 + AI 递增），用于测试 server 动态更新。

    前 64 个 DI 通道按位打包（8 通道/字节，共 8 字节），
    后 32 个 AI 通道各占 2 字节（16 位大端，共 64 字节）。
    每轮让 DI 一个 bit 走位、AI 写入递增整数，直到 Ctrl+C 停止。
    """
    print(f"开始循环发送 72 字节数据（DI 走位 + AI 递增），间隔 {interval}s（Ctrl+C 停止）")
    saved_trace = client.transaction.trace_packet
    client.transaction.trace_packet = lambda sending, data: data  # 循环时关闭原始报文打印
    cycle = 0
    try:
        while True:
            buf = bytearray(72)
            bit = cycle % 64
            buf[bit // 8] = 1 << (bit % 8)
            ai_val = cycle & 0xFFFF
            for k in range(32):
                buf[8 + 2 * k] = (ai_val >> 8) & 0xFF
                buf[8 + 2 * k + 1] = ai_val & 0xFF
            regs = [int.from_bytes(buf[i:i + 2], "big") for i in range(0, 72, 2)]
            resp = client.write_registers(0, regs, device_id=device_id)
            if resp.isError():
                print(f"  第 {cycle} 次写入失败: {resp}")
            else:
                print(f"  第 {cycle} 次: DI 通道 {bit + 1} = 1, AI 值 = {ai_val}")
            cycle += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  循环发送已停止")
    finally:
        client.transaction.trace_packet = saved_trace


def run_loop_send_slave2(client, device_id, interval):
    """循环发送从站2 输入通道数据（48 DI 位打包 + 8 AI 16 位，共 22 字节）。

    前 48 个 DI 通道按位打包（8 通道/字节，共 6 字节），
    后 8 个 AI 通道各占 2 字节（16 位大端，共 16 字节）。
    每轮让 DI 一个 bit 走位、AI 写入递增整数，直到 Ctrl+C 停止。
    """
    print(f"开始循环发送从站2 数据（48 DI 走位 + 8 AI 递增），间隔 {interval}s（Ctrl+C 停止）")
    saved_trace = client.transaction.trace_packet
    client.transaction.trace_packet = lambda sending, data: data  # 循环时关闭原始报文打印
    cycle = 0
    try:
        while True:
            buf = bytearray(22)
            bit = cycle % 48
            buf[bit // 8] = 1 << (bit % 8)
            ai_val = cycle & 0xFFFF
            for k in range(8):
                buf[6 + 2 * k] = (ai_val >> 8) & 0xFF
                buf[6 + 2 * k + 1] = ai_val & 0xFF
            regs = [int.from_bytes(buf[i:i + 2], "big") for i in range(0, 22, 2)]
            resp = client.write_registers(0, regs, device_id=device_id)
            if resp.isError():
                print(f"  第 {cycle} 次写入失败: {resp}")
            else:
                print(f"  第 {cycle} 次: DI 通道 {bit + 1} = 1, AI 值 = {ai_val}")
            cycle += 1
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  循环发送已停止")
    finally:
        client.transaction.trace_packet = saved_trace


def run_read_output(client, device_id):
    """读取从站1 输出通道打包值（36 个寄存器 = 72 字节）并打印。"""
    resp = client.read_holding_registers(0, count=36, device_id=device_id)
    if resp.isError():
        print(f"  读取失败: {resp}")
        return
    regs = resp.registers
    data = b"".join(r.to_bytes(2, "big") for r in regs)
    print(f"  寄存器({len(regs)}个): {regs}")
    print(f"  数据({len(data)}字节): {data.hex(' ')}")
    # DO: 64 通道，按位打包（8 通道/字节）
    do_on = []
    for i in range(8):
        byte = data[i] if i < len(data) else 0
        for j in range(8):
            if (byte >> j) & 1:
                do_on.append(i * 8 + j + 1)
    print(f"  DO 值为1的通道: {do_on}")
    # AO: 32 通道，2 字节/通道（16 位大端）
    ao = []
    for k in range(32):
        base = 8 + 2 * k
        hi = data[base] if base < len(data) else 0
        lo = data[base + 1] if base + 1 < len(data) else 0
        ao.append((hi << 8) | lo)
    print(f"  AO 通道值: {ao}")


def run_read_output_slave2(client, device_id):
    """读取从站2 输出通道打包值（19 个寄存器 = 38 字节）并打印。"""
    resp = client.read_holding_registers(0, count=19, device_id=device_id)
    if resp.isError():
        print(f"  读取失败: {resp}")
        return
    regs = resp.registers
    data = b"".join(r.to_bytes(2, "big") for r in regs)
    print(f"  寄存器({len(regs)}个): {regs}")
    print(f"  数据({len(data)}字节): {data.hex(' ')}")
    # DO: 48 通道，按位打包（8 通道/字节，共 6 字节）
    do_on = []
    for i in range(6):
        byte = data[i] if i < len(data) else 0
        for j in range(8):
            if (byte >> j) & 1:
                do_on.append(i * 8 + j + 1)
    print(f"  DO 值为1的通道: {do_on}")
    # AO: 16 通道，2 字节/通道（16 位大端）
    ao = []
    for k in range(16):
        base = 6 + 2 * k
        hi = data[base] if base < len(data) else 0
        lo = data[base + 1] if base + 1 < len(data) else 0
        ao.append((hi << 8) | lo)
    print(f"  AO 通道值: {ao}")


def run_demo(client, device_id):
    """运行一次读写演示。"""
    print("== 读取保持寄存器 [0..9] ==")
    show_result(client.read_holding_registers(0, count=10, device_id=device_id))
    print("== 写入保持寄存器 [0]=123 ==")
    show_result(client.write_register(0, 123, device_id=device_id))
    print("== 回读保持寄存器 [0] ==")
    show_result(client.read_holding_registers(0, count=1, device_id=device_id))
    print("== 读取输入寄存器 [0..9] ==")
    show_result(client.read_input_registers(0, count=10, device_id=device_id))
    print("== 读取离散输入 [0..9] ==")
    show_result(client.read_discrete_inputs(0, count=10, device_id=device_id))
    print("== 读取线圈 [0..9] ==")
    show_result(client.read_coils(0, count=10, device_id=device_id))


def main(argv=None):
    parser = argparse.ArgumentParser(description="Modbus TCP 客户端模拟器")
    parser.add_argument("--host", default="127.0.0.1", help="服务器地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=5020, help="服务器端口（默认 5020）")
    parser.add_argument("--device-id", type=int, default=1, help="从站设备 ID（默认 1）")
    args = parser.parse_args(argv)

    client = ModbusTcpClient(args.host, port=args.port, trace_packet=make_trace())
    if not client.connect():
        print(f"连接失败: {args.host}:{args.port}")
        return 1

    print(f"已连接 {args.host}:{args.port}，设备 ID={args.device_id}")
    print(HELP)

    try:
        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not run_command(client, args.device_id, line):
                break
    finally:
        client.close()
        print("连接已关闭")
    return 0


if __name__ == "__main__":
    sys.exit(main())
