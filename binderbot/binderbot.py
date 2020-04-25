"""Main module.

Much of this code was adopted from Hubtraf, by Yuvi Panda:
https://github.com/yuvipanda/hubtraf/blob/master/hubtraf/user.py
"""

from enum import Enum, auto
import aiohttp
import socket
import uuid
import random
from yarl import URL
import asyncio
import async_timeout
import structlog
import time
import json
import textwrap
import re
from contextlib import asynccontextmanager

import nbformat
from nbconvert.preprocessors import ClearOutputPreprocessor

from binderbot import OperationError
from .kernel import Kernel

logger = structlog.get_logger()


class BinderUser:
    class States(Enum):
        CLEAR = 1
        # LOGGED_IN = 2
        BINDER_STARTED = 3
        KERNEL_STARTED = 4

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={'User-Agent': 'BinderBot-cli v0.1'})
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.close()

    def __init__(self, binder_url, repo, ref):
        """
        A simulated BinderHub user.
        binderhub_url - base url of the binderhub
        """
        self.binder_url = URL(binder_url)
        self.repo = repo
        self.ref = ref
        self.state = BinderUser.States.CLEAR
        self.log = logger.bind()

    async def start_binder(self, timeout=3000, spawn_refresh_time=20):
        start_time = time.monotonic()
        self.log.msg(f'Binder: Starting', action='binder-start', phase='start')

        try:
            launch_url = self.binder_url / 'build/gh/' / self.repo / self.ref
            self.log.msg(f'Binder: Get {launch_url}', action='binder-start', phase='get-launch-url')
            resp = await self.session.get(launch_url)
        except Exception as e:
            self.log.msg('Binder: Failed {}'.format(str(e)), action='binder-start', phase='attempt-failed')
            raise e

        async for line in resp.content:
            line = line.decode('utf8')
            if line.startswith('data:'):
                data = json.loads(line.split(':', 1)[1])
                phase = data.get('phase')
                if phase == 'failed':
                    self.log.msg('Binder: Build Failed {}'.format(data['message']), action='binder-start',
                                 phase='build-failed', duration=time.monotonic() - start_time)
                    raise OperationError()
                if phase == 'ready':
                    self.notebook_url = URL(data['url'])
                    self.token = data['token']
                    self.log.msg(f'Binder: Got token and url ({self.notebook_url})', action='binder-ready',
                                 phase='build-token', duration=time.monotonic() - start_time)
                    break
                if time.monotonic() - start_time >= timeout:
                    self.log.msg('Binder: Build timeout', action='binder-start', phase='failed', duration=time.monotonic() - start_time)
                    raise OperationError()
                self.log.msg(f'Binder: Waiting on event stream (phase: {phase})', action='binder-start', phase='event-stream')


        # todo: double check phase is really always "ready" at this point
        self.state = BinderUser.States.BINDER_STARTED

    async def shutdown_binder(self):
        """
        Shut down running binder instance.
        """
        # Ideally, we will talk to the hub API to shut this down
        # However, the token we get is just a notebook auth token, *not* a hub auth otken
        # So we can't make requests to the hub API.
        # FIXME: Provide hub auth tokens from binderhub API
        nbclient = NotebookClient(self.session, self.notebook_url, self.token, self.log)
        async with nbclient.start_kernel() as kernel:
            await kernel.run_code("""
            import os
            import signal
            # FIXME: Wait a bit, and send SIGKILL otherwise
            os.kill(1, signal.SIGTERM)
            """)


class NotebookClient:
    """
    Client for doing operations against a notebook server
    """
    def __init__(self, session: aiohttp.ClientSession, url: URL, token: str, log: structlog.BoundLogger):
        # FIXME: If we get this from BinderBot, will it close properly?
        self.session = session
        self.url = url
        self.token = token
        self.log = log

        self.auth_headers = {
            'Authorization': f'token {self.token}'
        }

    @asynccontextmanager
    async def start_kernel(self):
        self.log.msg('Kernel: Starting', action='kernel-start', phase='start')
        start_time = time.monotonic()

        try:
            resp = await self.session.post(self.url / 'api/kernels', headers=self.auth_headers)
        except Exception as e:
            self.log.msg('Kernel: Start failed {}'.format(str(e)), action='kernel-start', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()

        if resp.status != 201:
            self.log.msg('Kernel: Start failed', action='kernel-start', phase='failed')
            raise OperationError()
        kernel_id = (await resp.json())['id']
        self.log.msg('Kernel: Started', action='kernel-start', phase='complete')
        k = Kernel(self, kernel_id)
        try:
            yield k
        finally:
            await k.stop_kernel()

    # https://github.com/jupyter/jupyter/wiki/Jupyter-Notebook-Server-API#notebook-and-file-contents-api
    async def get_contents(self, path):
        resp = await self.session.get(self.url / 'api/contents' / path, headers=self.auth_headers)
        resp_json = await resp.json()
        return resp_json['content']

    async def put_contents(self, path, nb_data):
        data = {'content': nb_data, "type": "notebook"}
        resp = await self.session.put(self.url / 'api/contents' / path,
                                      json=data, headers=self.auth_headers)
        resp.raise_for_status()


    async def list_notebooks(self):
        code = """
        import os, fnmatch, json
        notebooks = [f for f in os.listdir() if fnmatch.fnmatch(f, '*.ipynb')]
        print(json.dumps(notebooks))
        """
        stdout, stderr = await self.run_code(code)
        return json.loads(stdout)

    async def upload_local_notebook(self, notebook_filename):
        nb = open_nb_and_strip_output(notebook_filename)
        # probably want to use basename instead
        await self.put_contents(notebook_filename, nb)


def open_nb_and_strip_output(fname):
    cop = ClearOutputPreprocessor()
    with open(fname) as f:
        nb = nbformat.read(f, as_version=4)
    cop.preprocess(nb, dict())
    return nb
