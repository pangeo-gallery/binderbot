"""Console script for binderbot."""
import asyncio
from functools import update_wrapper
import os
import sys

import click
import nbformat

from .binderbot import BinderUser

# https://github.com/pallets/click/issues/85#issuecomment-43378930
def coro(f):
    f = asyncio.coroutine(f)
    def wrapper(*args, **kwargs):
        loop = asyncio.get_event_loop()
        return loop.run_until_complete(f(*args, **kwargs))
    return update_wrapper(wrapper, f)

@click.command()
@click.option('--binder-url', default='https://binder.pangeo.io',
              help='URL of binder service.')
@click.option('--repo', help='The GitHub repo to use for the binder image.')
@click.option('--ref', default='master',
              help='The branch or commit`.')
@click.option('--output-dir', nargs=1,
              type=click.Path(exists=True, file_okay=False, dir_okay=True),
              help='Directory in which to save the executed notebooks.')
@click.option("--nb-timeout", default=600,
              help="Maximum execution time (in second) for each notebook.")
@click.option("--binder-start-timeout", default=600,
              help="Maximum time (in seconds) to wait for binder to start.")
@click.option("--pass-env-var", "-e", multiple=True,
              help="Environment variables to pass to the binder execution environment.")
@click.option("--download/--no-download", default=True,
              help="Whether to use download the executed notebooks.")
@click.argument('filenames', nargs=-1, type=click.Path(exists=True))
@coro
async def main(binder_url, repo, ref, output_dir, nb_timeout,
               binder_start_timeout, pass_env_var, download, filenames):
    """Run local notebooks on a remote binder."""

    # validate filename inputs
    non_notebook_files = [fname for fname in filenames
                          if not fname.endswith('.ipynb')]
    if len(non_notebook_files) > 0:
        raise ValueError(f"The following filenames don't look like notebooks: "
                         f"{non_notebook_files}")

    click.echo(f"✅ Found the following notebooks: {filenames}")
    click.echo(f"⌛️ Starting binder\n"
               f"     binder_url: {binder_url}\n"
               f"     repo: {repo}\n"
               f"     ref: {ref}")

    extra_env_vars = {k: os.environ[k] for k in pass_env_var}

    # inputs look good, start up binder
    async with BinderUser(binder_url, repo, ref) as jovyan:
        await jovyan.run(filenames,
                         binder_start_timeout=binder_start_timeout,
                         nb_timeout=nb_timeout,
                         extra_env_vars=extra_env_vars, download=download,
                         output_dir=output_dir)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
