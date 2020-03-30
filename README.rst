=========
Binderbot
=========


.. image:: https://img.shields.io/pypi/v/binderbot.svg
        :target: https://pypi.python.org/pypi/binderbot

.. image:: https://travis-ci.org/pangeo-gallery/binderbot.svg?branch=master
    :target: https://travis-ci.org/pangeo-gallery/binderbot

.. image:: https://readthedocs.org/projects/binderbot/badge/?version=latest
        :target: https://binderbot.readthedocs.io/en/latest/?badge=latest
        :alt: Documentation Status

.. image:: https://img.shields.io/github/license/pangeo-gallery/binderbot
        :alt: GitHub


A simple CLI to interact with binder.

Example Usage
-------------

.. code-block::

   $ python -m binderbot.cli --help
   Usage: cli.py [OPTIONS] [FILENAMES]...

     Run local notebooks on a remote binder.

   Options:
     --binder-url TEXT       URL of binder service.
     --repo TEXT             The GitHub repo to use for the binder image.
     --ref TEXT              The branch or commit`.
     --output-dir DIRECTORY  Directory in which to save the executed notebooks.
     --help                  Show this message and exit.


* Free software: BSD license

Features
--------

* TODO

Credits
-------

This code was adapted from Hubtraf_, written by Yuvi Panda.

This package was created with Cookiecutter_ and the `audreyr/cookiecutter-pypackage`_ project template.

.. _Cookiecutter: https://github.com/audreyr/cookiecutter
.. _`audreyr/cookiecutter-pypackage`: https://github.com/audreyr/cookiecutter-pypackage
.. _Hubtraf: https://github.com/yuvipanda/hubtraf
