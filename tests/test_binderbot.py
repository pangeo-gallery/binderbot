#!/usr/bin/env python

"""Tests for `binderbot` package."""

import os

import typing
import asyncio
import pytest
from click.testing import CliRunner
import nbformat
from pathlib import Path
import subprocess
import secrets
from tempfile import TemporaryDirectory
import socket
import time
import yarl
import structlog
import aiohttp

from binderbot import binderbot
from binderbot import cli

class LocalNotebookServer:
    def __init__(self, url: yarl.URL, token: str, cwd: Path):
        self.url = url
        self.token = token
        self.cwd = cwd


@pytest.fixture
def free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", 0))
    portnum = s.getsockname()[1]
    s.close()
    return portnum

@pytest.fixture
async def local_notebook(free_port):
    token = secrets.token_hex(16)
    with TemporaryDirectory() as tmpdir:
        #free_port = 8888
        #token = 'fdbdeca87bd6cf39d366519f5cc0c9c7c994647f6696e8bb'
        cwd = Path(tmpdir)
        cmd = [
            'jupyter', 'notebook',
            f'--NotebookApp.token={token}',
            '--port', str(free_port),
            '--no-browser'
        ]
        proc = await asyncio.create_subprocess_exec(*cmd, cwd=tmpdir)
        # FIXME: Use a http health-check, not a timed wait
        await asyncio.sleep(2)
        # localhost is important, aiohttp doesn't really like to authenticate against IPs
        yield LocalNotebookServer(yarl.URL.build(scheme='http', host='localhost', port=free_port), token=token, cwd=cwd)

        proc.terminate()
        await proc.wait()


def make_code_notebook(cells: typing.List[str]):
    nbdata = {
        'cells': [
            {
                'cell_type': 'code',
                'execution_count': None,
                'metadata': {},
                'outputs': [],
                'source': cell
            } for cell in cells
        ],
        'metadata': {
            'kernelspec': {
                'display_name': 'Python 3',
                'language': 'python',
                'name': 'python3'
            },
            'language_info': {
                'codemirror_mode': {
                    'name': 'ipython',
                    'version': 3
                },
                'file_extension': '.py',
                'mimetype': 'text/x-python',
                'name': 'python',
                'nbconvert_exporter': 'python',
                'pygments_lexer': 'ipython3',
                'version': '3.8.1'
            }
        },
        'nbformat': 4,
        'nbformat_minor': 4
    }
    return nbformat.from_dict(nbdata)


@pytest.fixture()
def binder_url():
    return 'https://mybinder.org'

@pytest.mark.asyncio
async def test_binder_start_stop(binder_url):
    """
    Test that our binder starts and stops
    """
    async with binderbot.BinderUser(binder_url, 'binder-examples/requirements', 'master') as jovyan:
        await jovyan.start_binder()
        headers = {'Authorization': f'token {jovyan.token}'}
        resp = await jovyan.session.get(
            jovyan.notebook_url / 'api/status',
            headers=headers
        )
        assert resp.status == 200

        await jovyan.shutdown_binder()
        resp = await jovyan.session.get(
            jovyan.notebook_url / 'api/status',
            headers=headers
        )

        assert resp.status == 503


@pytest.mark.asyncio
async def test_nbclient_run_code(local_notebook: LocalNotebookServer):
    log = structlog.get_logger().bind()
    async with aiohttp.ClientSession() as session:
        nbclient = binderbot.NotebookClient(session, local_notebook.url, local_notebook.token, log)

        async with nbclient.start_kernel() as kernel:
            stdout, stderr = await kernel.run_code(f"""
            print('hi')
            """)

        assert stderr.strip() == ""
        assert stdout.strip() == 'hi'


@pytest.mark.asyncio
async def test_upload(local_notebook: LocalNotebookServer):
    log = structlog.get_logger().bind()
    async with aiohttp.ClientSession() as session:
        nbclient = binderbot.NotebookClient(session, local_notebook.url, local_notebook.token, log)

        fname = "example-notebook.ipynb"
        filepath = local_notebook.cwd / fname
        input_notebook = make_code_notebook(["print('hello')"])
        with open(filepath, 'w', encoding='utf-8') as f:
            nbformat.write(input_notebook, f)

        async with nbclient.start_kernel() as kernel:
            await kernel.execute_notebook(
                fname,
                timeout=60,
                )
        nb_data = await nbclient.get_contents(fname)
        nb = nbformat.from_dict(nb_data)

        cell1 = nb['cells'][0]['outputs'][0]['text']
        assert cell1 == "hello\n"