import asyncio
import logging
import threading

from pymodbus.server import ModbusTcpServer as _PymodbusTcpServer
from pymodbus.simulator import SimData, SimDevice
from pymodbus.simulator.simdata import DataType

logger = logging.getLogger("SimTest")


class ModbusTcpServer:
    """Modbus TCP 服务器封装。

    在后台线程中运行 asyncio 事件循环，避免阻塞 GUI。
    通过 pymodbus 的 trace_packet 提供收发数据回调：

    - on_data_received(data: bytes)：收到 client 请求时回调
    - on_data_sent(data: bytes)：向 client 发送响应时回调
    """

    def __init__(self, host="0.0.0.0", port=5020,
                 on_data_received=None, on_data_sent=None):
        self.host = host
        self.port = port
        self.on_data_received = on_data_received
        self.on_data_sent = on_data_sent

        self._server = None
        self._loop = None
        self._thread = None
        self._ready = threading.Event()
        self.running = False

    def _build_device(self):
        """构建默认从站设备（数据存储），后续可依据通道配置调整。"""
        size = 1000
        coils = [SimData(0, count=size, values=0, datatype=DataType.BITS)]
        discrete = [SimData(0, count=size, values=0, datatype=DataType.BITS)]
        holding = [SimData(0, count=size, values=0, datatype=DataType.REGISTERS)]
        inputs = [SimData(0, count=size, values=0, datatype=DataType.REGISTERS)]
        # simdata 顺序：(coils, discrete inputs, holding registers, input registers)
        return SimDevice(0, simdata=(coils, discrete, holding, inputs))

    def _trace_packet(self, sending, data):
        # sending=True 表示发送，False 表示接收
        if sending:
            if self.on_data_sent:
                self.on_data_sent(data)
        else:
            if self.on_data_received:
                self.on_data_received(data)
        return data

    def start(self):
        """启动服务（后台线程）。"""
        if self.running:
            logger.warning("Modbus TCP 服务已在运行")
            return False

        self._ready.clear()
        self._thread = threading.Thread(target=self._run,
                                        name="ModbusTcpServer", daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout=5):
            logger.error("Modbus TCP 服务启动超时")
            return False

        self.running = True
        logger.info("Modbus TCP 服务已启动 %s:%s", self.host, self.port)
        return True

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._async_run())
        except Exception as exc:
            logger.error("Modbus TCP 服务运行异常: %s", exc)
        finally:
            self._loop.close()

    async def _async_run(self):
        self._server = _PymodbusTcpServer(
            self._build_device(),
            address=(self.host, self.port),
            trace_packet=self._trace_packet,
        )
        self._ready.set()
        await self._server.serve_forever()

    def stop(self):
        """停止服务。"""
        if not self.running:
            return

        if self._server and self._loop and self._loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._server.shutdown(), self._loop)
            try:
                future.result(timeout=5)
            except Exception:
                pass

        if self._thread:
            self._thread.join(timeout=5)

        self.running = False
        self._server = None
        logger.info("Modbus TCP 服务已停止")
