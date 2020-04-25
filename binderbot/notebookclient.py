"""Main module.

Much of this code was adopted from Hubtraf, by Yuvi Panda:
https://github.com/yuvipanda/hubtraf/blob/master/hubtraf/user.py
"""

import aiohttp
import random
from yarl import URL
import structlog
import time
import json
from contextlib import asynccontextmanager

import nbformat
from nbconvert.preprocessors import ClearOutputPreprocessor

from binderbot import OperationError
from .kernel import Kernel

logger = structlog.get_logger()


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
    async def start_kernel(self, cleanup=True):
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
            if cleanup:
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
