#!./.venv/bin/python
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl)
import asyncio
from collections import deque

import uvloop


async def run_in_serial(task_list):
    q = asyncio.Queue()
    for task in task_list:
        await q.put(task)
    lst_result = []
    for i in range(len(task_list)):
        co = await q.get()
        result = await co
        lst_result.append(result)
    return lst_result


async def run_command_get_output(*args, cwd=None):
    if cwd is not None:
        process = await asyncio.create_subprocess_exec(
            *args,
            # stdout must a pipe to be accessible as process.stdout
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    else:
        process = await asyncio.create_subprocess_exec(
            *args,
            # stdout must a pipe to be accessible as process.stdout
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    # Wait for the subprocess to finish
    stdout, stderr = await process.communicate()
    return stdout.decode()


async def run_command_get_output_and_status(*args, cwd=None):
    if cwd is not None:
        process = await asyncio.create_subprocess_exec(
            *args,
            # stdout must a pipe to be accessible as process.stdout
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    else:
        process = await asyncio.create_subprocess_exec(
            *args,
            # stdout must a pipe to be accessible as process.stdout
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    # Wait for the subprocess to finish
    stdout, stderr = await process.communicate()
    return stdout.decode(), stderr.decode(), process.returncode


def print_summary_task(task_list):
    for task in task_list:
        print(task.cr_code.co_name)


def execute(config, lst_task, use_uvloop=False):

    if not config.no_parallel and asyncio.get_event_loop().is_closed():
        asyncio.set_event_loop(asyncio.new_event_loop())

    if config.no_parallel:
        return_value = asyncio.run(run_in_serial(lst_task))
    elif config.max_process:
        pool = AsyncioPool(config.max_process)
        for task in lst_task:
            pool.add_coro(task)
        try:
            return_value = pool.run_until_complete()
        finally:
            pool.close()
    else:
        # Use maximal resource
        if use_uvloop:
            uvloop.install()
        loop = asyncio.get_event_loop()
        if config.debug:
            loop.set_debug(True)
        try:
            commands = asyncio.gather(*lst_task)
            return_value = loop.run_until_complete(commands)
        finally:
            loop.close()
    return return_value


class AsyncioPool:
    # TODO check to replace this pool by https://github.com/dano/aioprocessing
    def __init__(self, concurrency, loop=None):
        """
        @param loop: asyncio loop
        @param concurrency: Maximum number of concurrently running tasks
        """
        self._loop = loop or asyncio.get_event_loop()
        self._concurrency = concurrency
        self._coros = deque([])  # All coroutines queued for execution
        self._futures = []  # All currently running coroutines
        self._lst_result = []

    def close(self):
        self._loop.close()

    def add_coro(self, coro):
        """
        @param coro: coroutine to add
        """
        self._coros.append(coro)
        self.print_status()

    def run_until_complete(self):
        self._loop.run_until_complete(self._wait_for_futures())
        return self._lst_result

    def print_status(self):
        print(
            " Status: coros:%s - futures:%s"
            % (len(self._coros), len(self._futures))
        )

    def _start_futures(self):
        num_to_start = self._concurrency - len(self._futures)
        num_to_start = min(num_to_start, len(self._coros))
        for _ in range(num_to_start):
            coro = self._coros.popleft()
            future = asyncio.ensure_future(coro, loop=self._loop)
            self._futures.append(future)
            self.print_status()

    async def _wait_for_futures(self):
        while len(self._coros) > 0 or len(self._futures) > 0:
            self._start_futures()
            futures_completed, futures_pending = await asyncio.wait(
                self._futures,
                loop=self._loop,
                return_when=asyncio.FIRST_COMPLETED,
            )

            for future in futures_completed:
                self._lst_result.append(future.result())
                self._futures.remove(future)
                self._start_futures()
