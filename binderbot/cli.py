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
@click.argument('filenames', nargs=-1, type=click.Path(exists=True))
@coro
async def main(binder_url, repo, ref, output_dir, nb_timeout,
               binder_start_timeout, filenames):
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

    # inputs look good, start up binder
    async with BinderUser(binder_url, repo, ref) as jovyan:
        await jovyan.start_binder(timeout=binder_start_timeout)
        await jovyan.start_kernel()
        click.echo(f"✅ Binder and kernel started successfully.")
        # could think about asyncifying this whole loop
        # for now, we run one notebook at a time to avoid overloading the binder
        errors = {}
        for fname in filenames:
            try:
                click.echo(f"⌛️ Uploading {fname}...", nl=False)
                await jovyan.upload_local_notebook(fname)
                click.echo("✅")
                click.echo(f"⌛️ Executing {fname}...", nl=False)
                await jovyan.execute_notebook(fname, timeout=nb_timeout)
                click.echo("✅")
                click.echo(f"⌛️ Downloading and saving {fname}...", nl=False)
                nb_data = await jovyan.get_contents(fname)
                nb = nbformat.from_dict(nb_data)
                output_fname = os.path.join(output_dir, fname) if output_dir else fname
                with open(output_fname, 'w', encoding='utf-8') as f:
                    nbformat.write(nb, f)
                click.echo("✅")
            except Exception as e:
                errors[fname] = e
                click.echo(f'❌ error running {fname}: {e}')

        await jovyan.stop_kernel()

        if len(errors) > 0:
            raise RuntimeError(str(errors))

        # TODO: shut down binder
        # await jovyan.shutdown_binder()
        # can we do this with a context manager so that it shuts down in case of errors?


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
