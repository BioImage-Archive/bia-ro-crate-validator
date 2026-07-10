import json
import logging
from pathlib import Path
from typing import Annotated

import typer
from rich.logging import RichHandler

from bia_ro_crate.models.ro_crate_generator_utils import generate_embeded_bia_context
from bia_ro_crate.validator import (
    ValidationProfile,
    ValidationResponseMode,
    bia_roc_validation,
)

bia_ro_crate = typer.Typer(
    name="bia-ro-crate", context_settings={"help_option_names": ["-h", "--help"]}
)

logging.basicConfig(
    level=logging.WARNING,
    format="%(message)s",
    datefmt="[%X]",
    handlers=[RichHandler()],
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
    level = {1: logging.INFO, 2: logging.DEBUG}.get(
        verbose, logging.NOTSET if verbose >= 3 else logging.WARNING
    )
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
    report_json: bool = False,
    profile: Annotated[
        ValidationProfile | None,
        typer.Option(
            "--profile",
            help="Apply an additional BIA application profile.",
        ),
    ] = None,
):
    if crate_path.is_file():
        crate_path = crate_path.parent

    if report_json:
        report = bia_roc_validation(
            crate_path, ValidationResponseMode.report, profile=profile
        )
        print(json.dumps(report, indent=2))
    else:
        bia_roc_validation(crate_path, profile=profile)


@bia_ro_crate.command("generate-context")
def generate_ro_crate_context(
    output_file: Annotated[
        Path,
        typer.Argument(
            help="Path to file where a the json-ld context should be written"
        ),
    ],
):
    context = generate_embeded_bia_context()

    with open(output_file, "w") as f:
        f.write(json.dumps(context, indent=2))

    
