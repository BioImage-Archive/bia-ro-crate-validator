import copy
import json
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from bia_ro_crate.cli import bia_ro_crate
from bia_ro_crate.core.bia_ro_crate_metadata import BIAROCrateMetadata
from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.core.file_list import FileList
from bia_ro_crate.core.validation import Severity
from bia_ro_crate.models import ro_crate_models as models
from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm
from bia_ro_crate.models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from bia_ro_crate.validator.profiles.bia_submission_v0 import SubmissionChecks


@pytest.fixture
def submission(tmp_path):
    context = {
        "bia": "http://bia/",
        "csvw": "http://www.w3.org/ns/csvw#",
        "Dataset": "http://schema.org/Dataset",
        "File": "http://schema.org/MediaObject",
        "Person": "http://schema.org/Person",
    }
    entities = [
        {
            "@id": "./",
            "@type": ["Dataset", "bia:Study"],
            "name": "Study",
            "description": "Study",
            "license": "https://creativecommons.org/publicdomain/zero/1.0/",
            "datePublished": "2020-01-01",
            "accessionId": "anything",
            "author": [{"@id": "#author"}],
            "hasPart": [{"@id": "#dataset"}, {"@id": "file_list.tsv"}],
        },
        {"@id": "#author", "@type": ["Person", "bia:Contributor"], "name": "Author"},
        {
            "@id": "#dataset",
            "@type": ["Dataset", "bia:Dataset"],
            "name": "Dataset",
            "associatedAnnotationMethod": [{"@id": "#method"}],
        },
        {
            "@id": "#method",
            "@type": "bia:AnnotationMethod",
            "name": "Method",
            "description": "Description",
            "methodType": ["Other"],
        },
        {
            "@id": "file_list.tsv",
            "@type": ["File", "bia:FileList", "csvw:Table"],
            "tableSchema": {"@id": "#schema"},
        },
        {
            "@id": "#schema",
            "@type": "csvw:Schema",
            "column": [
                {"@id": "#filepath"},
                {"@id": "#dataset-column"},
                {"@id": "#type"},
                {"@id": "#source"},
            ],
        },
        {
            "@id": "#filepath",
            "@type": "csvw:Column",
            "columnName": "file_path",
            "propertyUrl": "http://bia/filePath",
        },
        {
            "@id": "#dataset-column",
            "@type": "csvw:Column",
            "columnName": "dataset",
            "propertyUrl": "http://schema.org/isPartOf",
        },
        {
            "@id": "#type",
            "@type": "csvw:Column",
            "columnName": "type",
            "propertyUrl": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        },
        {
            "@id": "#source",
            "@type": "csvw:Column",
            "columnName": "source_image",
            "propertyUrl": "http://bia/associatedSourceImage",
        },
    ]
    rows = "file_path\tdataset\ttype\tsource_image\nimage.tif\t#dataset\thttp://bia/Image\t\n"

    def write(data=None, tsv=None):
        raw_entities = data if data is not None else entities
        model_by_type = {
            "bia:Study": models.Study,
            "bia:Contributor": models.Contributor,
            "bia:Dataset": models.Dataset,
            "bia:AnnotationMethod": models.AnnotationMethod,
            "bia:FileList": models.FileList,
            "csvw:Schema": models.TableSchema,
            "csvw:Column": models.Column,
            "bia:BioSample": models.BioSample,
            "bia:Taxon": models.Taxon,
            "bia:SpecimenImagingPreparationProtocol": models.SpecimenImagingPreparationProtocol,
            "bia:ImageAcquisitionProtocol": models.ImageAcquisitionProtocol,
            "bia:SignalChannel": models.SignalChannelInformation,
            "bia:Affiliation": models.Affiliation,
        }
        objects = {}
        for entity in raw_entities:
            types = entity["@type"]
            types = [types] if isinstance(types, str) else types
            cls = next(model_by_type[t] for t in types if t in model_by_type)
            obj = cls.model_validate(entity)
            objects[obj.id] = obj
        parsed_context = SimpleJSONLDContext(
            prefixes={k: v for k, v in context.items() if k in ("bia", "csvw")},
            terms=[
                ContextTerm(full_uri=v, field_name=k)
                for k, v in context.items()
                if k not in ("bia", "csvw")
            ],
        )
        metadata = BIAROCrateMetadata(objects, parsed_context, tmp_path)
        file_list = metadata.get_file_list_entity()
        schema = metadata.get_object(file_list.tableSchema.id)
        columns = {ref.id: metadata.get_object(ref.id) for ref in schema.column}
        frame = pd.read_csv(StringIO(tsv if tsv is not None else rows), sep="\t")
        parsed_file_list = FileList(
            schema=columns, data=frame, ro_crate_id=file_list.id
        )
        return SubmissionChecks(BIASubmissionMetadata(metadata, parsed_file_list)).run()

    return copy.deepcopy(entities), write


def errors(issues):
    return [
        issue.format_message() for issue in issues if issue.severity >= Severity.ERROR
    ]


def test_annotation_dataset_and_existing_doi_accession(submission):
    entities, write = submission
    entities[0]["doi"] = "10.1234/example"
    assert not errors(write(entities))
    entities[0]["accessionId"] = ""
    assert not any("accessionId" in issue for issue in errors(write(entities)))


def test_dataset_requires_complete_imaging_branch_or_annotation(submission):
    entities, write = submission
    entities[2].pop("associatedAnnotationMethod")
    entities[2]["associatedBiologicalEntity"] = [{"@id": "#bio"}]
    assert any("annotation method" in msg for msg in errors(write(entities)))


def test_imaging_only_dataset_with_complete_metadata(submission):
    entities, write = submission
    dataset = entities[2]
    dataset.pop("associatedAnnotationMethod")
    dataset.update(
        {
            "associatedBiologicalEntity": [{"@id": "#sample"}],
            "associatedSpecimenImagingPreparationProtocol": [{"@id": "#prep"}],
            "associatedImageAcquisitionProtocol": [{"@id": "#acq"}],
        }
    )
    entities.extend(
        [
            {
                "@id": "#sample",
                "@type": "bia:BioSample",
                "name": "Sample",
                "description": "Sample",
                "organismClassification": [{"@id": "#taxon"}],
            },
            {"@id": "#taxon", "@type": "bia:Taxon", "scientificName": "Species"},
            {
                "@id": "#prep",
                "@type": "bia:SpecimenImagingPreparationProtocol",
                "name": "Preparation",
                "description": "Preparation",
            },
            {
                "@id": "#acq",
                "@type": "bia:ImageAcquisitionProtocol",
                "name": "Acquisition",
                "description": "Acquisition",
                "imagingInstrumentDescription": "Instrument",
                "imagingMethodName": ["Microscopy"],
                "fbbiId": ["unrestricted model value"],
            },
        ]
    )
    rows = "file_path\tdataset\ttype\nimage.tif\t#dataset\thttp://bia/Image\n"
    assert not errors(write(entities, rows))


def test_each_imaging_dataset_requires_its_own_image_and_row(submission):
    entities, write = submission
    entities[2]["associatedImageAcquisitionProtocol"] = [{"@id": "#acq"}]
    entities.append(
        {
            "@id": "#acq",
            "@type": "bia:ImageAcquisitionProtocol",
            "name": "Acq",
            "description": "Description",
            "imagingInstrumentDescription": "Instrument",
            "imagingMethodName": ["microscopy"],
            "fbbiId": ["https://example.org/fbbi"],
        }
    )
    issues = errors(
        write(
            entities,
            "file_path\tdataset\ttype\tsource_image\nother.tif\t#other\thttp://bia/Image\t\n",
        )
    )
    assert any("at least one file-list row" in msg for msg in issues)
    assert any("at least one image" in msg for msg in issues)
    assert not errors(write(entities))


def test_all_file_list_columns_require_schema_definitions(submission):
    entities, write = submission
    with pytest.raises(ValueError, match="Schema does not contain columns"):
        write(
            entities,
            "file_path\tdataset\ttype\tsource_image\textra\nimage.tif\t#dataset\thttp://bia/Image\t\tvalue\n",
        )


def test_repeated_labels_across_datasets_are_allowed(submission):
    entities, write = submission
    entities[0]["hasPart"].append({"@id": "#dataset2"})
    entities[5]["column"].append({"@id": "#label"})
    entities.extend(
        [
            {
                "@id": "#dataset2",
                "@type": ["Dataset", "bia:Dataset"],
                "name": "Dataset 2",
                "associatedAnnotationMethod": [{"@id": "#method"}],
            },
            {
                "@id": "#label",
                "@type": "csvw:Column",
                "columnName": "label",
                "propertyUrl": "http://schema.org/name",
            },
        ]
    )
    rows = (
        "file_path\tdataset\ttype\tsource_image\tlabel\n"
        "one.tif\t#dataset\thttp://bia/Image\t\tshared\n"
        "two.tif\t#dataset2\thttp://bia/Image\t\tshared\n"
    )
    assert not errors(write(entities, rows))


def test_reference_target_type_is_checked(submission):
    entities, write = submission
    entities[3]["@type"] = "bia:BioSample"
    entities[3]["organismClassification"] = []
    issues = errors(write(entities))
    assert any(
        "associatedAnnotationMethod" in msg and "must have type" in msg
        for msg in issues
    )


def test_ontology_subclasses_are_accepted_for_reference_targets(submission):
    entities, write = submission
    entities[1]["memberOf"] = [{"@id": "#org"}]
    entities.extend(
        [
            {"@id": "#org", "@type": "bia:Affiliation", "name": "Org"},
            {
                "@id": "#sample",
                "@type": "bia:BioSample",
                "name": "Sample",
                "description": "Sample",
                "organismClassification": [{"@id": "#taxon"}],
                "growthProtocol": {"@id": "#prep"},
            },
            {"@id": "#taxon", "@type": "bia:Taxon", "scientificName": "Species"},
            {
                "@id": "#prep",
                "@type": "bia:SpecimenImagingPreparationProtocol",
                "name": "Preparation",
                "description": "Preparation",
            },
        ]
    )
    assert not errors(write(entities))
    entities[-1]["@type"] = "bia:SignalChannel"
    assert any(
        "growthProtocol" in issue and "must have type" in issue
        for issue in errors(write(entities))
    )


def test_compact_iri_identifiers_are_checked_against_source_ids(submission):
    entities, write = submission
    entities[2]["associatedBiologicalEntity"] = [{"@id": "bia:sample"}]
    entities.extend(
        [
            {
                "@id": "bia:sample",
                "@type": "bia:BioSample",
                "name": "Sample",
                "description": "Sample",
                "organismClassification": [{"@id": "#taxon"}],
            },
            {"@id": "#taxon", "@type": "bia:Taxon", "scientificName": "Species"},
        ]
    )
    assert not errors(write(entities))


@pytest.mark.parametrize(
    "value", ["http://bia/Image", "http://bia/AnnotationData", "http://bia/File"]
)
def test_permitted_file_types(submission, value):
    entities, write = submission
    rows = f"file_path\tdataset\ttype\tsource_image\nfile\t#dataset\t{value}\t\n"
    assert not errors(write(entities, rows))


@pytest.mark.parametrize("value", ["bia:Image", "http://example.org/Other", ""])
def test_unpermitted_file_types(submission, value):
    entities, write = submission
    rows = f"file_path\tdataset\ttype\tsource_image\nfile\t#dataset\t{value}\t\n"
    assert any("unsupported type" in issue for issue in errors(write(entities, rows)))


@pytest.mark.parametrize(
    "entity_id", ["https://example.org/dataset", "_:dataset", "//example.org/dataset"]
)
def test_dataset_and_protocol_identifiers_must_be_relative(submission, entity_id):
    entities, write = submission
    entities[2]["@id"] = entity_id
    entities[3]["@id"] = "https://example.org/method"
    issues = errors(write(entities))
    assert sum("relative IRI" in issue for issue in issues) == 2


def test_relative_path_identifier_is_allowed(submission):
    entities, write = submission
    entities[2]["@id"] = "datasets/dataset"
    entities[0]["hasPart"][0]["@id"] = "datasets/dataset"
    rows = "file_path\tdataset\ttype\tsource_image\nimage.tif\tdatasets/dataset\thttp://bia/Image\t\n"
    assert not errors(write(entities, rows))


def test_unknown_profile_rejected():
    result = CliRunner().invoke(bia_ro_crate, ["validate", ".", "--profile", "unknown"])
    assert result.exit_code != 0
    assert "unknown" in result.output


def test_cli_passes_selected_profile(tmp_path, monkeypatch):
    import bia_ro_crate.cli as cli

    calls = []
    monkeypatch.setattr(
        cli, "bia_roc_validation", lambda path, **kwargs: calls.append((path, kwargs))
    )
    runner = CliRunner()
    assert runner.invoke(bia_ro_crate, ["validate", str(tmp_path)]).exit_code == 0
    assert (
        runner.invoke(
            bia_ro_crate, ["validate", str(tmp_path), "--profile", "bia-submission-v0"]
        ).exit_code
        == 0
    )
    assert [call[1]["profile"] for call in calls] == ["minimal", "bia-submission-v0"]


def test_minimal_source_reference_wrong_type_remains_an_error():
    import pandas as pd

    from bia_ro_crate.core.parser.file_list_parser import FileListParser
    from bia_ro_crate.models.linked_data.ontology_terms import BIA

    issues = []
    FileListParser._check_row_reference_against_filelist(
        pd.Series({"file_path": "annotation.tif", "source_image": ["source.tif"]}),
        {"source.tif": "http://bia/AnnotationData"},
        {},
        {"source_image": BIA.Image},
        "file_path",
        issues,
    )
    assert len(issues) == 1
    assert issues[0].severity == Severity.ERROR


@pytest.mark.parametrize(
    "name", ["source image", "source_image", "associated_source_image"]
)
def test_annotation_source_column_name_and_property(submission, name):
    entities, write = submission
    entities[-1]["columnName"] = name
    rows = f"filepath\tdataset\ttype\t{name}\nimage.tif\t#dataset\thttp://bia/Image\t\n"
    entities[6]["columnName"] = "filepath"
    assert not errors(write(entities, rows))
    entities[-1]["propertyUrl"] = "http://bia/sourceImageLabel"
    assert any(
        "annotation dataset requires" in msg.lower()
        for msg in errors(write(entities, rows))
    )


def test_existing_minimal_and_submission_profile_api(tmp_path):
    from bia_ro_crate.validator import bia_roc_validation

    fixture = Path(__file__).parent / "validator/input_ro_crate/test_typical_ro_crate"
    data = json.loads((fixture / "ro-crate-metadata.json").read_text())
    by_id = {entity["@id"]: entity for entity in data["@graph"]}
    by_id["./"]["description"] = "A study"
    by_id["#Imaging%20Dataset"]["associatedBiologicalEntity"] = [{"@id": "#sample"}]
    by_id["#Imaging%20Dataset"]["associatedSpecimenImagingPreparationProtocol"] = [
        {"@id": "#prep"}
    ]
    by_id["#Imaging%20Method"]["imagingMethodName"] = ["microscopy"]
    by_id["#Imaging%20Method"]["fbbiId"] = ["http://example.org/fbbi"]
    by_id["#Annotation%20Method"]["methodType"] = ["Other"]
    by_id["_:col4"]["columnName"] = "source_image"
    by_id["_:col4"]["propertyUrl"] = "http://bia/associatedSourceImage"
    data["@graph"].extend(
        [
            {
                "@id": "#sample",
                "@type": ["bia:BioSample"],
                "name": "Sample",
                "description": "A sample",
                "organismClassification": [
                    {"@id": "https://www.ncbi.nlm.nih.gov/datasets/taxonomy/9606"}
                ],
            },
            {
                "@id": "https://www.ncbi.nlm.nih.gov/datasets/taxonomy/9606",
                "@type": ["bia:Taxon"],
                "scientificName": "Homo sapiens",
            },
            {
                "@id": "#prep",
                "@type": ["bia:SpecimenImagingPreparationProtocol"],
                "name": "Preparation",
                "description": "Prepared sample",
            },
        ]
    )
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps(data))
    (tmp_path / "file_list.tsv").write_text(
        (fixture / "file_list.tsv")
        .read_text()
        .replace("source_image_label", "source_image")
    )
    default_report = bia_roc_validation(tmp_path, "report")
    explicit_minimal_report = bia_roc_validation(tmp_path, "report", profile="minimal")
    assert default_report == explicit_minimal_report
    result = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert set(result) == {"highest_error_level", "issues"}
    assert result["issues"]["ERROR"] == []
    for severity, issues in default_report["issues"].items():
        assert all(issue in result["issues"][severity] for issue in issues)

    path = tmp_path / "file_list.tsv"
    original = path.read_text()
    lines = original.splitlines()
    row = lines[1].split("\t")
    row[5] = row[4]  # Point to the annotation row, which is not a BIA Image.
    lines[1] = "\t".join(row)
    path.write_text("\n".join(lines) + "\n")
    for profile in ("minimal", "bia-submission-v0"):
        result = bia_roc_validation(tmp_path, "report", profile=profile)
        assert any(
            "expected 'http://bia/Image'" in issue["message"]
            for issue in result["issues"]["ERROR"]
        )
    path.write_text(original)

    # A column absent from the schema makes the minimal parser fail before it
    # can build FileList; the submission profile must still report the cause.
    lines = path.read_text().splitlines()
    path.write_text(
        "\n".join([lines[0] + "\textra"] + [line + "\tvalue" for line in lines[1:]])
        + "\n"
    )
    result = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert any(
        "Schema does not contain columns" in issue["message"]
        and "extra" in issue["message"]
        for issue in result["issues"]["ERROR"]
    )
