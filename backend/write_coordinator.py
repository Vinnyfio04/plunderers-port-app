"""Bounded FIFO ownership of application writes; backpressure instead of dropping events."""
import asyncio
import inspect
import time


class WriteCoordinator:
    def __init__(self):
        self.queue = asyncio.Queue(maxsize=2048)
        self.task = None
        self.completed = 0
        self.last_latency_ms = 0

    async def run(self, function):
        if self.task is None:
            self.task = asyncio.create_task(self._worker())
        future = asyncio.get_running_loop().create_future()
        await self.queue.put((function,future,time.perf_counter()))
        return await asyncio.shield(future)

    async def _worker(self):
        while True:
            function, future, started = await self.queue.get()
            try:
                result = function()
                if inspect.isawaitable(result):
                    result = await result
                if not future.done():
                    future.set_result(result)
                self.completed += 1
                self.last_latency_ms = (time.perf_counter()-started)*1000
            except Exception as error:
                if not future.done():
                    future.set_exception(error)
            finally:
                self.queue.task_done()

    async def close(self):
        await self.queue.join()
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
