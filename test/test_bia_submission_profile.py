import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bia_ro_crate.cli import bia_ro_crate
from bia_ro_crate.validator import (
    ValidationResponseMode,
    bia_submission_roc_validation,
)


runner = CliRunner()


@pytest.fixture
def submission_crate(tmp_path: Path) -> Path:
    source = (
        Path(__file__).parent
        / "validator"
        / "input_ro_crate"
        / "test_typical_ro_crate"
    )
    crate = tmp_path / "submission-crate"
    shutil.copytree(source, crate)

    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    graph = metadata["@graph"]
    objects_by_id = {entity["@id"]: entity for entity in graph}
    objects_by_id["./"]["description"] = "A BIA submission test study."

    imaging_dataset = objects_by_id["#Imaging%20Dataset"]
    imaging_dataset["@type"].append("bia:RembiDataset")
    imaging_dataset.update(
        {
            "description": "A REMBI imaging dataset.",
            "associatedBiologicalEntity": [{"@id": "#BioSample"}],
            "associatedSpecimen": {"@id": "#Specimen"},
            "associatedSpecimenImagingPreparationProtocol": [
                {"@id": "#Specimen%20Preparation"}
            ],
        }
    )

    annotation_dataset = objects_by_id["#Annotation%20Dataset"]
    annotation_dataset["@type"].append("bia:MifaDataset")
    annotation_dataset["description"] = "A MIFA annotation dataset."

    objects_by_id["#Imaging%20Method"]["imagingMethodName"] = [
        "Transmission electron microscopy"
    ]
    objects_by_id["#Annotation%20Method"]["methodType"] = ["manual"]

    graph.extend(
        [
            {
                "@id": "#BioSample",
                "@type": ["bia:BioSample"],
                "name": "Cultured cells",
                "description": "Cells used for imaging.",
                "organismClassification": [{"@id": "#Taxon"}],
            },
            {
                "@id": "#Taxon",
                "@type": ["bia:Taxon"],
                "scientificName": "Homo sapiens",
            },
            {
                "@id": "#Specimen%20Preparation",
                "@type": ["bia:SpecimenImagingPreparationProtocol"],
                "name": "Fixation and staining",
                "description": "Cells were fixed and stained before imaging.",
            },
            {
                "@id": "#Specimen",
                "@type": ["bia:Specimen"],
                "biologicalEntity": [{"@id": "#BioSample"}],
                "imagingPreparationProtocol": [
                    {"@id": "#Specimen%20Preparation"}
                ],
            },
        ]
    )
    metadata_path.write_text(json.dumps(metadata, indent=2))
    return crate


def _profile_report(crate: Path) -> dict:
    return bia_submission_roc_validation(crate, ValidationResponseMode.report)


def _error_messages(report: dict) -> list[str]:
    return [issue["message"] for issue in report["issues"]["ERROR"]]


def test_bia_submission_profile_accepts_valid_rembi_and_mifa_submission(
    submission_crate: Path,
):
    report = _profile_report(submission_crate)

    assert report["issues"]["ERROR"] == []


def test_bia_submission_profile_applies_only_mifa_requirements_to_mifa_submission(
    submission_crate: Path,
):
    metadata_path = submission_crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    for entity in metadata["@graph"]:
        if entity.get("@id") == "#Imaging%20Dataset":
            entity["@type"].remove("bia:RembiDataset")
    metadata_path.write_text(json.dumps(metadata, indent=2))

    report = _profile_report(submission_crate)

    assert report["issues"]["ERROR"] == []


""" def test_bia_submission_profile_warns_for_missing_recommended_properties(
    submission_crate: Path,
):
    report = _profile_report(submission_crate)

    warning_messages = [issue["message"] for issue in report["issues"]["WARNING"]]
    assert any(
        "[rembi/taxon-required-properties]" in message
        and "commonName" in message
        for message in warning_messages
    ) """


def test_bia_submission_profile_requires_taxon_reference_for_biosample(
    submission_crate: Path,
):
    metadata_path = submission_crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    for entity in metadata["@graph"]:
        if entity.get("@id") == "#Taxon":
            entity["@type"] = ["bia:Protocol"]
            entity["name"] = "Not a taxon"
            entity["description"] = "A valid object of the wrong type."
    metadata_path.write_text(json.dumps(metadata, indent=2))

    report = _profile_report(submission_crate)

    assert any(
        "[rembi/biosample-present]" in message
        and "organismClassification -> bia:Taxon" in message
        for message in _error_messages(report)
    )


def test_bia_submission_profile_requires_rembi_dataset_associations(
    submission_crate: Path,
):
    metadata_path = submission_crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    for entity in metadata["@graph"]:
        if entity.get("@id") == "#Imaging%20Dataset":
            del entity["associatedSpecimen"]
    metadata_path.write_text(json.dumps(metadata, indent=2))

    report = _profile_report(submission_crate)

    assert any(
        "[rembi/dataset-with-required-associations]" in message
        for message in _error_messages(report)
    )


def test_bia_submission_profile_requires_rembi_or_mifa_dataset_type(
    submission_crate: Path,
):
    metadata_path = submission_crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    for entity in metadata["@graph"]:
        entity_type = entity.get("@type", [])
        if isinstance(entity_type, list):
            entity["@type"] = [
                type_name
                for type_name in entity_type
                if type_name not in {"bia:RembiDataset", "bia:MifaDataset"}
            ]
    metadata_path.write_text(json.dumps(metadata, indent=2))

    report = _profile_report(submission_crate)

    assert any(
        "[bia-submission/at-least-one-rembi-or-mifa-dataset]" in message
        for message in _error_messages(report)
    )


def test_bia_submission_profile_requires_dataset_column_name(
    submission_crate: Path,
):
    metadata_path = submission_crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    for entity in metadata["@graph"]:
        if entity.get("columnName") == "dataset":
            entity["columnName"] = "dataset_id"
    metadata_path.write_text(json.dumps(metadata, indent=2))

    file_list_path = submission_crate / "file_list.tsv"
    file_list_path.write_text(file_list_path.read_text().replace("dataset", "dataset_id", 1))

    report = _profile_report(submission_crate)

    assert any(
        "[bia-submission/file-list-dataset-column]" in message
        for message in _error_messages(report)
    )


def test_bia_submission_profile_requires_image_file_list_row(
    submission_crate: Path,
):
    file_list_path = submission_crate / "file_list.tsv"
    file_list_path.write_text(
        file_list_path.read_text().replace("http://bia/Image", "http://bia/AnnotationData")
    )

    report = _profile_report(submission_crate)

    assert any(
        "[rembi/file-list-image-row-present]" in message
        for message in _error_messages(report)
    )


def test_validate_command_accepts_bia_submission_profile(submission_crate: Path):
    result = runner.invoke(
        bia_ro_crate,
        ["validate", "--profile", "bia-submission", str(submission_crate)],
    )

    assert result.exit_code == 0
