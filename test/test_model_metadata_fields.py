import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from bia_ro_crate.models import ro_crate_models as models

FIXTURES = Path(__file__).parent / "validator" / "input_ro_crate"
STUDY = next(
    entity
    for entity in json.loads(
        (
            FIXTURES / "test_minimal_valid_ro_crate" / "ro-crate-metadata.json"
        ).read_text()
    )["@graph"]
    if entity["@id"] == "./"
)


def test_study_dates_keep_native_types_and_iso_json_without_changing_input():
    supplied = STUDY | {"datePublished": "2024-02-29", "dateModified": "2024-03-01"}
    before = json.loads(json.dumps(supplied))
    study = models.Study.model_validate(supplied)
    assert study.datePublished == date(2024, 2, 29)
    assert type(study.datePublished) is date
    assert study.dateModified == date(2024, 3, 1)
    assert type(study.dateModified) is date
    dumped = json.loads(study.model_dump_json(by_alias=True))
    assert dumped["datePublished"] == "2024-02-29"
    assert dumped["dateModified"] == "2024-03-01"
    assert supplied == before


@pytest.mark.parametrize("field", ["datePublished", "dateModified"])
@pytest.mark.parametrize("value", ["2023-02-29", "2024-02-29T01:00:00Z"])
def test_invalid_or_inexact_study_dates_are_not_silently_truncated(field, value):
    with pytest.raises(ValidationError) as error:
        models.Study.model_validate(STUDY | {field: value})
    assert error.value.errors()[0]["loc"] == (field,)
