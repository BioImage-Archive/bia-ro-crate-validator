from copy import deepcopy
from pathlib import Path

import pandas as pd
import pytest

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.models.ro_crate_models import Column


@pytest.fixture(scope="session")
def parsed_submission():
    parser = ROCrateParser(
        Path(__file__).parents[1] / "validator/input_ro_crate/test_typical_ro_crate"
    )
    parser.parse()
    return parser.result


@pytest.fixture
def submission(parsed_submission):
    result = deepcopy(parsed_submission)
    frame = parsed_submission.file_list.data
    result.file_list.data = pd.DataFrame(
        deepcopy(frame.to_numpy().tolist()),
        columns=frame.columns,
        index=frame.index,
        dtype=object,
    ).astype(frame.dtypes)
    return result


@pytest.fixture
def new_column():
    return Column(
        **{
            "@id": "#voxel-x",
            "@type": "csvw:Column",
            "columnName": "voxel_x",
            "propertyUrl": "http://bia/voxelSizeX",
        }
    )
