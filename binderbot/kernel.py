from . import OperationError
import uuid
import time
import aiohttp
import textwrap
import re

# https://stackoverflow.com/questions/14693701/how-can-i-remove-the-ansi-escape-sequences-from-a-string-in-python
def _ansi_escape(text):
    return re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])').sub('', text)

class Kernel:
    """
    Represents a running jupyter kernel
    """

    def __init__(self, nbclient, kernel_id: str):
        self.nbclient = nbclient
        self.kernel_id = kernel_id
        self.log = nbclient.log

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
        channel_url = self.nbclient.url / 'api/kernels' / self.kernel_id / 'channels'
        self.log.msg('WS: Connecting', action='kernel-connect', phase='start')
        is_connected = False
        try:
            async with self.nbclient.session.ws_connect(channel_url) as ws:
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


    async def stop_kernel(self):
        self.log.msg('Kernel: Stopping', action='kernel-stop', phase='start')
        start_time = time.monotonic()
        try:
            resp = await self.nbclient.session.delete(self.nbclient.url / 'api/kernels' / self.kernel_id, headers=self.nbclient.auth_headers)
        except Exception as e:
            self.log.msg('Kernel:Failed Stopped {}'.format(str(e)), action='kernel-stop', phase='failed')
            raise OperationError()

        if resp.status != 204:
            self.log.msg('Kernel:Failed Stopped {}'.format(str(resp)), action='kernel-stop', phase='failed')
            raise OperationError()

        self.log.msg('Kernel: Stopped', action='kernel-stop', phase='complete')
