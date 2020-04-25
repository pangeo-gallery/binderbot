"""Main module.

Much of this code was adopted from Hubtraf, by Yuvi Panda:
https://github.com/yuvipanda/hubtraf/blob/master/hubtraf/user.py
"""

from enum import Enum, auto
import aiohttp
from yarl import URL
import structlog
import time
import json


from binderbot import OperationError
from .kernel import Kernel
from .notebookclient import NotebookClient

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
        # Don't try to stop the kernel when we are done executin
        # We don't expect the notebook server to be around still
        async with nbclient.start_kernel(cleanup=False) as kernel:
            await kernel.run_code("""
            import os
            import signal
            # FIXME: Wait a bit, and send SIGKILL otherwise
            os.kill(1, signal.SIGTERM)
            """)