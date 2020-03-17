"""Console script for binderbot."""
import sys
import os
import click
import nbformat
from .binderbot import BinderUser

@click.command()
@click.option('--binder-url', default='https://binder.pangeo.io',
              help='URL of binder service.')
@click.option('--repo', help='The GitHub repo to use for the binder image.')
@click.option('--ref', defualt='master',
              help='The branch or commit`.')
@click.option('--output-dir', nargs=1,
              type=click.Path(exists=True, file_okay=False, dir_okay=True),
              help='Directory in which to save the executed notebooks.')
@click.argument('filenames', nargs=-1, type=click.Path(exists=True),
                help='Paths to Jupyter notebooks to run on the remote binder.')
def main(binder_url, repo, ref, output_dir, filenames):
    """Run local notebooks on a remote binder."""

    # validate filename inputs
    basenames = [basename(fname) for fname in filenames]
    non_notebook_files = [fname for fname in filenames
                          if not fname.endswith('.ipynb')]
    if len(non_notebook_files) > 0:
        raise ValueError(f"The following filenames don't look like notebooks: "
                         f"{non_notebook_files}")

    # inputs look good, start up binder
    async with BinderUser(binder_url, repo, ref) as jovyan:
        await jovyan.start_binder()
        await jovyan.start_kernel()

        # run one notebook at a time to avoid overloading the binder
        for fname in filenames:
            await jovyan.upload_local_notebook(fname)
            await jovyan.execute_notebook(nbfile)
            nb_data = await jovyan.get_contents(nbfile)
            output_fname = os.path.join(output_dir, fname) if output_dir else fname
            with open(output_fname, 'w', encoding='utf-8') as f:
                nbformat.write(nb_data, f)

        await jovyan.stop_kernel()

        # TODO: shut down binder
        # await jovyan.shutdown_binder()
        # can we do this with a context manager so that it shuts down in case of errors?


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
