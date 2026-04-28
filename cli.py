import logging
from pathlib import Path
from typing import Annotated
import json
import typer
from rich.logging import RichHandler

from bia_ro_crate.validator import bia_roc_validation

bia_ro_crate = typer.Typer(name="bia-ro-crate", context_settings={"help_option_names": ["-h", "--help"]})

logging.basicConfig(
    level=logging.WARNING, format="%(message)s", datefmt="[%X]", handlers=[RichHandler()]
)


@bia_ro_crate.callback()
def main(
    verbose: Annotated[
        int,
        typer.Option(
            "--verbose",
            "-v",
            count=True,
            help="Increase logging verbosity (-v INFO, -vv DEBUG, -vvv NOTSET).",
        ),
    ] = 0,
):
    level = {1: logging.INFO, 2: logging.DEBUG}.get(verbose, logging.NOTSET if verbose >= 3 else logging.WARNING)
    logging.getLogger().setLevel(level)


@bia_ro_crate.command("validate")
def validate_ro_crate(
    crate_path: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Path to the ro-crate root directory (or ro-crate-metadata.json)",
        ),
    ],
    report_json: bool = False
):
    if crate_path.is_file():
        crate_path = crate_path.parent

    if report_json:
        report = bia_roc_validation(crate_path, "report")
        print(json.dumps(report, indent=2))
    else:
        bia_roc_validation(crate_path)
