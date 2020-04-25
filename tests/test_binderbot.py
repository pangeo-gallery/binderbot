#!/usr/bin/env python

"""Tests for `binderbot` package."""

import os

import pytest
from click.testing import CliRunner
import nbformat

from binderbot import binderbot
from binderbot import cli


@pytest.fixture()
def example_nb_data():
    nbdata = {'cells': [{'cell_type': 'code',
                       'execution_count': None,
                       'metadata': {},
                       'outputs': [],
                       'source': 'import socket\nprint(socket.gethostname())'},
                      {'cell_type': 'code',
                       'execution_count': None,
                       'metadata': {},
                       'outputs': [],
                       'source': 'import os\nprint(os.environ["MY_VAR"])'}],
                     'metadata': {'kernelspec': {'display_name': 'Python 3',
                       'language': 'python',
                       'name': 'python3'},
                      'language_info': {'codemirror_mode': {'name': 'ipython', 'version': 3},
                       'file_extension': '.py',
                       'mimetype': 'text/x-python',
                       'name': 'python',
                       'nbconvert_exporter': 'python',
                       'pygments_lexer': 'ipython3',
                       'version': '3.8.1'}},
                     'nbformat': 4,
                     'nbformat_minor': 4}
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

def test_cli_upload_execute_download(tmp_path, example_nb_data):
    """Test the CLI."""

    os.chdir(tmp_path)
    fname = "example_notebook.ipynb"
    with open(fname, 'w', encoding='utf-8') as f:
        nbformat.write(example_nb_data, f)

    env = {"MY_VAR": "SECRET"}
    runner = CliRunner(env=env)
    args = ["--binder-url", "http://mybinder.org",
            "--repo", "binder-examples/requirements",
            "--ref", "master", "--nb-timeout", "10",
            "--pass-env-var",  "MY_VAR",
            fname]
    result = runner.invoke(cli.main, args)
    assert result.exit_code == 0, result.output

    with open(fname) as f:
        nb = nbformat.read(f, as_version=4)

    hostname = nb['cells'][0]['outputs'][0]['text']
    assert hostname.startswith('jupyter-binder-')
    remote_env_var_value = nb['cells'][1]['outputs'][0]['text']
    assert remote_env_var_value.rstrip() == env['MY_VAR']