#!/usr/bin/env python3
# © 2021-2025 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

import asyncio
from collections import deque

try:
    import uvloop
except ImportError:
    uvloop = None


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


async def run_shell_get_output(cmd, cwd=None):
    if cwd is not None:
        process = await asyncio.create_subprocess_shell(
            cmd,
            # stdout must a pipe to be accessible as process.stdout
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
        )
    else:
        process = await asyncio.create_subprocess_shell(
            cmd,
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


def print_summary_task(task_list, lst_task_name=None):
    for i, task in enumerate(task_list):
        if lst_task_name:
            task_name = lst_task_name[i]
            print(f"{i} - {task.cr_code.co_name} - {task_name}")
        else:
            print(f"{i} - {task.cr_code.co_name}")


def execute(config, lst_task, use_uvloop=False):
    error_detected = False
    return_value = None

    # --- Mode 1 : pas de parallélisme → déjà OK avec asyncio.run ---
    if config.no_parallel:
        # run_in_serial doit être une coroutine (async def)
        try:
            if use_uvloop and uvloop is not None:
                # À faire AVANT la création de la loop
                asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
            return_value = asyncio.run(run_in_serial(lst_task))
        except Exception as e:
            error_detected = True
            print(e)
        return return_value, error_detected

    # --- Mode 2 : AsyncioPool (on suppose qu'il gère sa loop lui-même) ---
    if config.max_process:
        pool = AsyncioPool(config.max_process)
        for task in lst_task:
            pool.add_coro(task)
        try:
            # API existante, on ne touche pas
            return_value = pool.run_until_complete()
        except Exception as e:
            error_detected = True
            print(e)
        finally:
            pool.close()
        return return_value, error_detected

    # --- Mode 3 : utilisation maximale des ressources avec asyncio.gather ---
    async def _run_max_resources(tasks, debug: bool):
        if debug:
            loop = asyncio.get_running_loop()
            loop.set_debug(True)
        # tasks doit être une liste de coroutines
        results = await asyncio.gather(*tasks)
        return results

    try:
        if use_uvloop and uvloop is not None:
            asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
        return_value = asyncio.run(_run_max_resources(lst_task, config.debug))
    except RuntimeError as e:
        # par ex. si tu appelles ça depuis un environnement où il y a
        # déjà une loop (Jupyter, certains frameworks)
        error_detected = True
        print(e)

    return return_value, error_detected


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
