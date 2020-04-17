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

import nbformat
from nbconvert.preprocessors import ClearOutputPreprocessor

logger = structlog.get_logger()

# https://stackoverflow.com/questions/14693701/how-can-i-remove-the-ansi-escape-sequences-from-a-string-in-python
def _ansi_escape(text):
    return re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', text)


class OperationError(Exception):
    pass


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
        # TODO: figure out how to shut down the binder using the API
        # can we use the jupyterhub API:
        # https://jupyterhub.readthedocs.io/en/stable/reference/rest.html#enabling-users-to-spawn-multiple-named-servers-via-the-api
        pass

    async def start_kernel(self):
        assert self.state == BinderUser.States.BINDER_STARTED

        self.log.msg('Kernel: Starting', action='kernel-start', phase='start')
        start_time = time.monotonic()

        try:
            headers = {'Authorization': f'token {self.token}'}
            resp = await self.session.post(self.notebook_url / 'api/kernels', headers=headers)
        except Exception as e:
            self.log.msg('Kernel: Start failed {}'.format(str(e)), action='kernel-start', phase='failed', duration=time.monotonic() - start_time)
            raise OperationError()

        if resp.status != 201:
            self.log.msg('Kernel: Start failed', action='kernel-start', phase='failed')
            raise OperationError()
        self.kernel_id = (await resp.json())['id']
        self.log.msg('Kernel: Started', action='kernel-start', phase='complete')
        self.state = BinderUser.States.KERNEL_STARTED


    async def stop_kernel(self):
        assert self.state == BinderUser.States.KERNEL_STARTED

        self.log.msg('Kernel: Stopping', action='kernel-stop', phase='start')
        start_time = time.monotonic()
        try:
            headers = {'Authorization': f'token {self.token}'}
            resp = await self.session.delete(self.notebook_url / 'api/kernels' / self.kernel_id, headers=headers)
        except Exception as e:
            self.log.msg('Kernel:Failed Stopped {}'.format(str(e)), action='kernel-stop', phase='failed')
            raise OperationError()

        if resp.status != 204:
            self.log.msg('Kernel:Failed Stopped {}'.format(str(resp)), action='kernel-stop', phase='failed')
            raise OperationError()

        self.log.msg('Kernel: Stopped', action='kernel-stop', phase='complete')
        self.state = BinderUser.States.BINDER_STARTED

    # https://github.com/jupyter/jupyter/wiki/Jupyter-Notebook-Server-API#notebook-and-file-contents-api
    async def get_contents(self, path):
        headers = {'Authorization': f'token {self.token}'}
        resp = await self.session.get(self.notebook_url / 'api/contents' / path, headers=headers)
        resp_json = await resp.json()
        return resp_json['content']


    async def put_contents(self, path, nb_data):
        headers = {'Authorization': f'token {self.token}'}
        data = {'content': nb_data, "type": "notebook"}
        resp = await self.session.put(self.notebook_url / 'api/contents' / path,
                                      json=data, headers=headers)
        resp.raise_for_status()

    def request_execute_code(self, msg_id, code):
        return {
            "header": {
                "msg_id": msg_id,
                "username": "jovyan",
                "msg_type": "execute_request",
                "version": "5.2"
            },
            "metadata": {},
            "content": {
                "code": textwrap.dedent(code),
                "silent": False,
                "store_history": True,
                "user_expressions": {},
                "allow_stdin": True,
                "stop_on_error": True
            },
            "buffers": [],
            "parent_header": {},
            "channel": "shell"
        }


    async def run_code(self, code):
        """Run code and return stdout, stderr."""
        assert self.state == BinderUser.States.KERNEL_STARTED

        channel_url = self.notebook_url / 'api/kernels' / self.kernel_id / 'channels'
        self.log.msg('WS: Connecting', action='kernel-connect', phase='start')
        is_connected = False
        try:
            async with self.session.ws_connect(channel_url) as ws:
                is_connected = True
                self.log.msg('WS: Connected', action='kernel-connect', phase='complete')
                start_time = time.monotonic()
                self.log.msg('Code Execute: Started', action='code-execute', phase='start')
                exec_start_time = time.monotonic()
                msg_id = str(uuid.uuid4())
                await ws.send_json(self.request_execute_code(msg_id, code))

                stdout = ''
                stderr = ''

                async for msg_text in ws:
                    if msg_text.type != aiohttp.WSMsgType.TEXT:
                        self.log.msg(
                            'WS: Unexpected message type',
                            action='code-execute', phase='failure',
                            iteration=iteration,
                            message_type=msg_text.type, message=str(msg_text),
                            duration=time.monotonic() - exec_start_time
                        )
                        raise OperationError()

                    msg = msg_text.json()

                    if 'parent_header' in msg and msg['parent_header'].get('msg_id') == msg_id:
                        # These are responses to our request
                        self.log.msg(f'Code Execute: Receive response', action='code-execute', phase='receive-stream',
                                     channel=msg['channel'], msg_type=msg['msg_type'])
                        if msg['channel'] == 'shell':
                            if msg['msg_type'] == 'execute_reply':
                                status = msg['content']['status']
                                if status == 'ok':
                                    self.log.msg('Code Execute: Status OK', action='code-execute', phase='success')
                                    break
                                else:
                                    self.log.msg('Code Execute: Status {status}', action='code-execute', phase='error')
                                    raise OperationError()
                        if msg['channel'] == 'iopub':
                            response = None
                            msg_type = msg.get('msg_type')
                            # don't really know what this is doing
                            #if msg_type == 'execute_result':
                            #    response = msg['content']['data']['text/plain']
                            if msg_type == 'error':
                                traceback = _ansi_escape('\n'.join(msg['content']['traceback']))
                                self.log.msg('Code Execute: Error', action='code-execute',
                                             phase='error',
                                             traceback=traceback)
                                raise OperationError()
                            elif msg_type == 'stream':
                                response = msg['content']['text']
                                name =  msg['content']['name']
                                if name == 'stdout':
                                    stdout += response
                                elif name == 'stderr':
                                    stderr += response
                                #print(response)
                self.log.msg(
                    'Code Execute: complete',
                    action='code-execute', phase='complete',
                    duration=time.monotonic() - exec_start_time)

                return stdout, stderr

        except Exception as e:
            if type(e) is OperationError:
                raise
            if is_connected:
                self.log.msg('Code Execute: Failed {}'.format(str(e)), action='code-execute', phase='failure')
            else:
                self.log.msg('WS: Failed {}'.format(str(e)), action='kernel-connect', phase='failure')
            raise OperationError()


    async def list_notebooks(self):
        code = """
        import os, fnmatch, json
        notebooks = [f for f in os.listdir() if fnmatch.fnmatch(f, '*.ipynb')]
        print(json.dumps(notebooks))
        """
        stdout, stderr = await self.run_code(code)
        return json.loads(stdout)

    async def execute_notebook(self, notebook_filename, timeout=600,
                               env_vars={}):
        env_var_str = str(env_vars)
        # https://nbconvert.readthedocs.io/en/latest/execute_api.html
        code = f"""
        import os
        import nbformat
        os.environ.update({env_var_str})
        from nbconvert.preprocessors import ExecutePreprocessor
        ep = ExecutePreprocessor(timeout={timeout})
        print("Processing {notebook_filename}")
        with open("{notebook_filename}") as f:
            nb = nbformat.read(f, as_version=4)
        ep.preprocess(nb, dict())
        print("OK")
        print("Saving {notebook_filename}")
        with open("{notebook_filename}", 'w', encoding='utf-8') as f:
            nbformat.write(nb, f)
        print("OK")
        """
        return await self.run_code(code)

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
