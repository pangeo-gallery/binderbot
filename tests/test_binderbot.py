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
    nbdata = {'cells': [{'cell_type': 'markdown',
               'metadata': {},
               'source': '# Test Pangeo Gallery'},
              {'cell_type': 'code',
               'execution_count': 1,
               'metadata': {},
               'outputs': [{'name': 'stdout',
                 'output_type': 'stream',
                 'text': "Today's date: 2020-03-12\n"}],
               'source': 'from datetime import date\ntoday = date.today()\nprint("Today\'s date:", today)'},
              {'cell_type': 'code',
               'execution_count': 2,
               'metadata': {},
               'outputs': [{'name': 'stdout',
                 'output_type': 'stream',
                 'text': 'Ryans-MacBook-Pro.local\n'}],
               'source': 'import socket\nprint(socket.gethostname())'},
              {'cell_type': 'code',
               'execution_count': 0,
               'metadata': {},
               'outputs': [],
               'source': 'import time\ntime.sleep(2)'},
              {'cell_type': 'code',
               'execution_count': None,
               'metadata': {},
               'outputs': [],
               'source': ''}],
             'metadata': {'kernelspec': {'display_name': 'Python 3',
               'language': 'python',
               'name': 'python3'},
              'language_info': {'codemirror_mode': {'name': 'ipython', 'version': 3},
               'file_extension': '.py',
               'mimetype': 'text/x-python',
               'name': 'python',
               'nbconvert_exporter': 'python',
               'pygments_lexer': 'ipython3',
               'version': '3.6.7'}},
             'nbformat': 4,
             'nbformat_minor': 4}
    return nbformat.from_dict(nbdata)

    return tmpdir


def test_cli_upload_execute_download(tmp_path, example_nb_data):
    """Test the CLI."""

    os.chdir(tmp_path)
    fname = "example_notebook.ipynb"
    with open(fname, 'w', encoding='utf-8') as f:
        nbformat.write(example_nb_data, f)

    runner = CliRunner()
    args = ["--binder-url", "http://mybinder.org",
            "--repo", "binder-examples/requirements",
            "--ref", "master", "--nb-timeout", "10",
            fname]
    result = runner.invoke(cli.main, args)
    assert result.exit_code == 0, result.output
    # assert 'binderbot.cli.main' in result.output

    with open(fname) as f:
        nb = nbformat.read(f, as_version=4)

    hostname = nb['cells'][2]['outputs'][0]['text']
    assert hostname.startswith('jupyter-binder-')

    # help_result = runner.invoke(cli.main, ['--help'])
    # assert help_result.exit_code == 0
    # assert '--help  Show this message and exit.' in help_result.output
