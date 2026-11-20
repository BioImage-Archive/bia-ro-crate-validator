import copy
import json
from io import StringIO
from pathlib import Path

import pandas as pd
import pytest

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

    def profile_validate(data=None, tsv=None):
        raw_entities = data if data is not None else entities
        model_by_type = {
            "bia:Study": models.Study,
            "bia:Contributor": models.Contributor,
            "bia:Dataset": models.Dataset,
            "bia:AnnotationMethod": models.AnnotationMethod,
            "bia:Protocol": models.Protocol,
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

    return copy.deepcopy(entities), profile_validate


def errors(issues):
    return [
        issue.format_message() for issue in issues if issue.severity >= Severity.ERROR
    ]


def test_bia_rembi_mifa_example_passes_submission_profile():
    from bia_ro_crate.validator import bia_roc_validation

    # Supplied BIA REMBI/MIFA example
    fixture = (
        Path(__file__).parent
        / "validator/input_ro_crate/test_bia_rembi_mifa_typical_ro_crate"
    )
    report = bia_roc_validation(fixture, "report", profile="bia-submission-v0")

    assert not report["issues"]["CRITICAL"]
    assert not report["issues"]["ERROR"]
    # This recommendation is specific to the profile, so it confirms that
    # the submission checks actually ran after the base parser succeeded.
    assert any("pubmedId" in issue["message"] for issue in report["issues"]["WARNING"])


def test_profile_checks_parsed_row_association_against_dataset(tmp_path):
    from bia_ro_crate.validator import bia_roc_validation

    fixture = (
        Path(__file__).parent
        / "validator/input_ro_crate/test_bia_rembi_mifa_typical_ro_crate"
    )
    metadata = json.loads((fixture / "ro-crate-metadata.json").read_text())
    graph = metadata["@graph"]
    table_schema = next(entity for entity in graph if entity.get("@id") == "_:ts0")
    table_schema["column"].append({"@id": "_:association-test"})
    graph.append(
        {
            "@id": "_:association-test",
            "@type": "csvw:Column",
            "columnName": "row_biosample",
            "propertyUrl": "http://bia/associatedBiologicalEntity",
        }
    )
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps(metadata))
    lines = (fixture / "file_list.tsv").read_text().splitlines()
    (tmp_path / "file_list.tsv").write_text(
        "\n".join(
            [
                lines[0] + "\trow_biosample",
                lines[1] + "\t",
                lines[2] + "\t",
                lines[3] + "\t#biosample",
            ]
            + [line + "\t" for line in lines[4:]]
        )
        + "\n"
    )
    report = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert any(
        "#masks" in issue["message"]
        and "does not include that association" in issue["message"]
        for issue in report["issues"]["ERROR"]
    )
    assert any(
        "row 2 must provide http://bia/associatedBiologicalEntity" in issue["message"]
        and "#images" in issue["message"]
        for issue in report["issues"]["ERROR"]
    )


def test_grouped_image_labels_pass_full_validation(tmp_path):
    from bia_ro_crate.validator import bia_roc_validation

    fixture = (
        Path(__file__).parent
        / "validator/input_ro_crate/test_bia_rembi_mifa_typical_ro_crate"
    )
    metadata = json.loads((fixture / "ro-crate-metadata.json").read_text())
    graph = metadata["@graph"]
    table_schema = next(entity for entity in graph if entity.get("@id") == "_:ts0")
    table_schema["column"].append({"@id": "_:label-test"})
    graph.append(
        {
            "@id": "_:label-test",
            "@type": "csvw:Column",
            "columnName": "image_label",
            "propertyUrl": "http://schema.org/name",
        }
    )
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps(metadata))
    lines = (fixture / "file_list.tsv").read_text().splitlines()
    (tmp_path / "file_list.tsv").write_text(
        "\n".join(
            [
                lines[0] + "\timage_label",
                lines[1] + "\timage-group",
                lines[2] + "\timage-group",
            ]
            + [line + "\t" for line in lines[3:]]
        )
        + "\n"
    )
    report = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert not report["issues"]["ERROR"]
    assert not report["issues"]["CRITICAL"]


@pytest.mark.parametrize(
    "property_iri",
    [
        "http://bia/associatedImageAcquisitionProtocol",
        "http://bia/associatedAnnotationMethod",
    ],
)
def test_forbidden_empty_association_column_fails_full_validation(
    tmp_path, property_iri
):
    from bia_ro_crate.validator import bia_roc_validation

    fixture = (
        Path(__file__).parent
        / "validator/input_ro_crate/test_bia_rembi_mifa_typical_ro_crate"
    )
    metadata = json.loads((fixture / "ro-crate-metadata.json").read_text())
    graph = metadata["@graph"]
    table_schema = next(entity for entity in graph if entity.get("@id") == "_:ts0")
    table_schema["column"].append({"@id": "_:association-test"})
    graph.append(
        {
            "@id": "_:association-test",
            "@type": "csvw:Column",
            "columnName": "forbidden",
            "propertyUrl": property_iri,
        }
    )
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps(metadata))
    lines = (fixture / "file_list.tsv").read_text().splitlines()
    (tmp_path / "file_list.tsv").write_text(
        "\n".join([lines[0] + "\tforbidden"] + [line + "\t" for line in lines[1:]])
        + "\n"
    )
    report = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert any(
        "must not use propertyUrl" in issue["message"]
        and property_iri in issue["message"]
        for issue in report["issues"]["ERROR"]
    )


def test_url_dataset_and_protocol_ids_pass_full_validation(tmp_path):
    from bia_ro_crate.validator import bia_roc_validation

    fixture = (
        Path(__file__).parent
        / "validator/input_ro_crate/test_bia_rembi_mifa_typical_ro_crate"
    )
    replacements = {
        "#masks": "https://example.org/dataset",
        "#crowdsourced-annotation-masks": "https://example.org/annotation-method",
    }
    metadata = (fixture / "ro-crate-metadata.json").read_text()
    file_list = (fixture / "file_list.tsv").read_text()
    for old, new in replacements.items():
        metadata = metadata.replace(f'"{old}"', f'"{new}"')
        file_list = file_list.replace(old, new)
    (tmp_path / "ro-crate-metadata.json").write_text(metadata)
    (tmp_path / "file_list.tsv").write_text(file_list)
    report = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert not report["issues"]["CRITICAL"]
    assert not report["issues"]["ERROR"]


def test_study_accepts_existing_doi_and_empty_accession(submission):
    entities, profile_validate = submission
    entities[0]["doi"] = "10.1234/example"
    assert not errors(profile_validate(entities))
    entities[0]["accessionId"] = ""
    assert not any(
        "accessionId" in issue for issue in errors(profile_validate(entities))
    )


def test_study_requires_a_referenced_bia_dataset_and_file_list(submission):
    entities, profile_validate = submission
    entities[0]["hasPart"] = [{"@id": "file_list.tsv"}, {"@id": "#author"}]
    issues = errors(profile_validate(entities))
    assert any("hasPart must reference #dataset" in issue for issue in issues)
    entities[0]["hasPart"] = [{"@id": "#dataset"}]
    issues = errors(profile_validate(entities))
    assert any("hasPart must reference file_list.tsv" in issue for issue in issues)


def test_study_requires_all_datasets_in_haspart(submission):
    entities, profile_validate = submission
    entities.append(
        {
            "@id": "#dataset2",
            "@type": ["Dataset", "bia:Dataset"],
            "name": "Dataset 2",
            "associatedAnnotationMethod": [{"@id": "#method"}],
        }
    )
    rows = (
        "file_path\tdataset\ttype\tsource_image\n"
        "one\t#dataset\thttp://bia/Image\t\n"
        "two\t#dataset2\thttp://bia/AnnotationData\t\n"
    )
    assert any(
        "hasPart must reference #dataset2" in issue
        for issue in errors(profile_validate(entities, rows))
    )
    entities[0]["hasPart"].append({"@id": "#dataset2"})
    assert not errors(profile_validate(entities, rows))


def test_study_license_restriction_and_no_profile_checks_for_other_fields(submission):
    entities, profile_validate = submission
    entities[0]["name"] = ""
    entities[0]["description"] = ""
    entities[0]["author"] = [{"@id": "#dataset"}]
    entities[0]["relatedPublication"] = [{"@id": "#dataset"}]
    issues = profile_validate(entities)
    assert not any(
        issue.location_description and "@id: ./" in issue.location_description
        for issue in issues
    )
    entities[0]["license"] = "https://example.org/license"
    assert any("Study license" in issue for issue in errors(profile_validate(entities)))


def test_dataset_requires_complete_imaging_branch_or_annotation(submission):
    entities, profile_validate = submission
    entities[2].pop("associatedAnnotationMethod")
    entities[2]["associatedBiologicalEntity"] = [{"@id": "#bio"}]
    assert any("annotation method" in msg for msg in errors(profile_validate(entities)))


def test_protocol_only_dataset_requires_another_primary_dataset(submission):
    entities, profile_validate = submission
    entities[2].pop("associatedAnnotationMethod")
    entities[2]["associatedProtocol"] = [{"@id": "#protocol"}]
    entities.append(
        {
            "@id": "#protocol",
            "@type": "bia:Protocol",
            "name": "Protocol",
            "description": "Protocol",
        }
    )
    assert any(
        "At least one dataset" in msg for msg in errors(profile_validate(entities))
    )
    entities[0]["hasPart"].append({"@id": "#dataset2"})
    entities.append(
        {
            "@id": "#dataset2",
            "@type": ["Dataset", "bia:Dataset"],
            "name": "Annotation",
            "associatedAnnotationMethod": [{"@id": "#method"}],
        }
    )
    rows = "file_path\tdataset\ttype\tsource_image\nfirst\t#dataset\thttp://bia/Image\t\nsecond\t#dataset2\thttp://bia/AnnotationData\t\n"
    assert not errors(profile_validate(entities, rows))


def test_submission_requires_a_bia_dataset(submission):
    entities, profile_validate = submission
    entities = [entity for entity in entities if entity["@id"] != "#dataset"]
    assert any(
        "Expected at least one BIA dataset" in issue
        for issue in errors(profile_validate(entities))
    )


def test_imaging_only_dataset_with_complete_metadata(submission):
    entities, profile_validate = submission
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
    assert not errors(profile_validate(entities, rows))


def test_each_imaging_dataset_requires_its_own_image_and_row(submission):
    entities, profile_validate = submission
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
        profile_validate(
            entities,
            "file_path\tdataset\ttype\tsource_image\nother.tif\t#other\thttp://bia/Image\t\n",
        )
    )
    assert any("at least one file-list row" in msg for msg in issues)
    assert any("at least one image" in msg for msg in issues)
    assert not errors(profile_validate(entities))


def test_all_file_list_columns_require_schema_definitions(submission):
    entities, profile_validate = submission
    with pytest.raises(ValueError, match="Schema does not contain columns"):
        profile_validate(
            entities,
            "file_path\tdataset\ttype\tsource_image\textra\nimage.tif\t#dataset\thttp://bia/Image\t\tvalue\n",
        )


@pytest.mark.parametrize("second_dataset", ["#dataset", "#dataset2"])
def test_labels_may_repeat_only_within_a_dataset(submission, second_dataset):
    entities, profile_validate = submission
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
        f"two.tif\t{second_dataset}\thttp://bia/Image\t\tshared\n"
        "three.tif\t#dataset2\thttp://bia/Image\t\tother\n"
    )
    issues = errors(profile_validate(entities, rows))
    if second_dataset == "#dataset2":
        assert any(
            "label 'shared' must not be shared across datasets" in issue
            for issue in issues
        )
    else:
        assert not issues


def test_reference_target_type_is_checked(submission):
    entities, profile_validate = submission
    entities[3]["@type"] = "bia:BioSample"
    entities[3]["organismClassification"] = []
    issues = errors(profile_validate(entities))
    assert any(
        "associatedAnnotationMethod" in msg and "must have type" in msg
        for msg in issues
    )


def test_growth_protocol_rejects_specialized_protocol_types(submission):
    entities, profile_validate = submission
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
    assert any(
        "growthProtocol" in issue and "must have type" in issue
        for issue in errors(profile_validate(entities))
    )
    entities[-1]["@type"] = "bia:Protocol"
    assert not errors(profile_validate(entities))
    entities[-1]["@type"] = "bia:SignalChannel"
    assert any(
        "growthProtocol" in issue and "must have type" in issue
        for issue in errors(profile_validate(entities))
    )


@pytest.mark.parametrize(
    "entity",
    [
        {
            "@id": "#growth",
            "@type": "bia:AnnotationMethod",
            "name": "Annotation",
            "description": "Annotation",
            "methodType": ["Other"],
        },
        {
            "@id": "#growth",
            "@type": "bia:ImageAcquisitionProtocol",
            "name": "Acquisition",
            "description": "Acquisition",
            "imagingInstrumentDescription": "Instrument",
            "imagingMethodName": ["Microscopy"],
            "fbbiId": ["term"],
        },
        {
            "@id": "#growth",
            "@type": "bia:SpecimenImagingPreparationProtocol",
            "name": "Preparation",
            "description": "Preparation",
        },
    ],
)
def test_growth_protocol_rejects_each_specialized_type(submission, entity):
    entities, profile_validate = submission
    entities.extend(
        [
            {
                "@id": "#sample",
                "@type": "bia:BioSample",
                "name": "Sample",
                "description": "Sample",
                "organismClassification": [{"@id": "#taxon"}],
                "growthProtocol": {"@id": "#growth"},
            },
            {"@id": "#taxon", "@type": "bia:Taxon", "scientificName": "Species"},
            entity,
        ]
    )
    assert any(
        "growthProtocol" in issue and "must have type" in issue
        for issue in errors(profile_validate(entities))
    )


def test_compact_iri_identifiers_are_checked_against_source_ids(submission):
    entities, profile_validate = submission
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
    assert not errors(profile_validate(entities))


@pytest.mark.parametrize(
    "value",
    [
        "http://bia/Image",
        "http://bia/AnnotationData",
        "",
        "bia:Image",
        "http://example.org/Other",
        "http://bia/File",
    ],
)
def test_file_type_values_are_not_restricted(submission, value):
    entities, profile_validate = submission
    rows = f"file_path\tdataset\ttype\tsource_image\nfile\t#dataset\t{value}\t\n"
    assert not errors(profile_validate(entities, rows))


def test_type_column_is_required(submission):
    entities, profile_validate = submission
    rows = "file_path\tdataset\tsource_image\nfile\t#dataset\t\n"
    assert any(
        "'type' column" in issue for issue in errors(profile_validate(entities, rows))
    )


@pytest.mark.parametrize(
    "property_iri,field,is_list",
    [
        ("http://bia/associatedBiologicalEntity", "associatedBiologicalEntity", True),
        (
            "http://bia/associatedImagingPreparationProtocol",
            "associatedSpecimenImagingPreparationProtocol",
            True,
        ),
        ("http://bia/associatedProtocol", "associatedProtocol", True),
        ("http://bia/associatedCreationProcess", "associatedCreationProcess", False),
        ("http://bia/associatedSubject", "associatedSpecimen", False),
    ],
)
def test_row_associations_must_be_in_dataset(submission, property_iri, field, is_list):
    entities, profile_validate = submission
    entities[5]["column"].append({"@id": "#association"})
    entities.append(
        {
            "@id": "#association",
            "@type": "csvw:Column",
            "columnName": "association",
            "propertyUrl": property_iri,
        }
    )
    rows = "file_path\tdataset\ttype\tsource_image\tassociation\nfile\t#dataset\thttp://bia/Image\t\t#target\n"
    assert any(
        "does not include that association" in issue
        for issue in errors(profile_validate(entities, rows))
    )
    if is_list:
        entities[2].setdefault(field, []).append({"@id": "#target"})
    else:
        entities[2][field] = {"@id": "#target"}
    assert not any(
        "does not include that association" in issue
        for issue in errors(profile_validate(entities, rows))
    )
    entities[2].pop(field)
    empty_rows = rows.replace("\t#target\n", "\t\n")
    assert not any(
        "does not include that association" in issue
        for issue in errors(profile_validate(entities, empty_rows))
    )


@pytest.mark.parametrize(
    "property_iri",
    [
        "http://bia/associatedImageAcquisitionProtocol",
        "http://bia/associatedAnnotationMethod",
    ],
)
def test_acquisition_and_annotation_association_columns_are_forbidden(
    submission, property_iri
):
    entities, profile_validate = submission
    entities[5]["column"].append({"@id": "#association"})
    entities.append(
        {
            "@id": "#association",
            "@type": "csvw:Column",
            "columnName": "any_name",
            "propertyUrl": property_iri,
        }
    )
    rows = "file_path\tdataset\ttype\tsource_image\tany_name\nfile\t#dataset\thttp://bia/Image\t\t\n"
    assert any(
        "must not use propertyUrl" in issue and property_iri in issue
        for issue in errors(profile_validate(entities, rows))
    )


@pytest.mark.parametrize(
    "property_iri,field,is_list",
    [
        ("http://bia/associatedBiologicalEntity", "associatedBiologicalEntity", True),
        (
            "http://bia/associatedImagingPreparationProtocol",
            "associatedSpecimenImagingPreparationProtocol",
            True,
        ),
        ("http://bia/associatedSubject", "associatedSpecimen", False),
    ],
)
def test_biosample_and_specimen_columns_require_values_when_dataset_has_association(
    submission, property_iri, field, is_list
):
    entities, profile_validate = submission
    entities[5]["column"].append({"@id": "#association"})
    entities.append(
        {
            "@id": "#association",
            "@type": "csvw:Column",
            "columnName": "association",
            "propertyUrl": property_iri,
        }
    )
    rows = "file_path\tdataset\ttype\tsource_image\tassociation\nfile\t#dataset\thttp://bia/Image\t\t\n"
    assert not any(
        "must provide" in issue for issue in errors(profile_validate(entities, rows))
    )
    entities[2][field] = [{"@id": "#target"}] if is_list else {"@id": "#target"}
    assert any(
        "must provide" in issue and property_iri in issue
        for issue in errors(profile_validate(entities, rows))
    )
    assert any(
        "must provide" in issue and property_iri in issue
        for issue in errors(profile_validate(entities, rows.replace("\t\n", "\t[]\n")))
    )
    assert not any(
        "must provide" in issue
        for issue in errors(
            profile_validate(entities, rows.replace("\t\n", "\t#target\n"))
        )
    )
    without_column = (
        "file_path\tdataset\ttype\tsource_image\nfile\t#dataset\thttp://bia/Image\t\n"
    )
    assert not any(
        "must provide" in issue
        for issue in errors(profile_validate(entities, without_column))
    )


def test_every_multivalued_row_association_must_be_in_dataset(submission):
    entities, profile_validate = submission
    entities[2]["associatedProtocol"] = [{"@id": "#one"}]
    entities[5]["column"].append({"@id": "#association"})
    entities.append(
        {
            "@id": "#association",
            "@type": "csvw:Column",
            "columnName": "association",
            "propertyUrl": "http://bia/associatedProtocol",
        }
    )
    rows = "file_path\tdataset\ttype\tsource_image\tassociation\nfile\t#dataset\thttp://bia/Image\t\t['#one', '#two']\n"
    issues = errors(profile_validate(entities, rows))
    assert any(
        "#two" in issue and "does not include that association" in issue
        for issue in issues
    )
    assert not any(
        "#one" in issue and "does not include that association" in issue
        for issue in issues
    )


def test_non_empty_rule_is_applied_per_dataset(submission):
    entities, profile_validate = submission
    entities[2]["associatedBiologicalEntity"] = [{"@id": "#sample"}]
    entities[0]["hasPart"].append({"@id": "#dataset2"})
    entities[5]["column"].append({"@id": "#association"})
    entities.extend(
        [
            {
                "@id": "#dataset2",
                "@type": ["Dataset", "bia:Dataset"],
                "name": "Other",
                "associatedAnnotationMethod": [{"@id": "#method"}],
            },
            {
                "@id": "#association",
                "@type": "csvw:Column",
                "columnName": "biosample",
                "propertyUrl": "http://bia/associatedBiologicalEntity",
            },
        ]
    )
    rows = "file_path\tdataset\ttype\tsource_image\tbiosample\nfirst\t#dataset\thttp://bia/Image\t\t\nsecond\t#dataset2\thttp://bia/Image\t\t\n"
    issues = errors(profile_validate(entities, rows))
    missing = [issue for issue in issues if "must provide" in issue]
    assert len(missing) == 1
    assert "row 2" in missing[0] and "#dataset" in missing[0]


def test_dataset_and_protocol_identifiers_must_not_be_blank_nodes(submission):
    entities, profile_validate = submission
    entities[2]["@id"] = "_:dataset"
    entities[3]["@id"] = "_:method"
    issues = errors(profile_validate(entities))
    assert sum("blank-node identifier" in issue for issue in issues) == 2


def test_dataset_and_protocol_url_identifiers_are_allowed(submission):
    entities, profile_validate = submission
    entities[2]["@id"] = "https://example.org/dataset"
    entities[3]["@id"] = "https://example.org/method"
    entities[0]["hasPart"][0]["@id"] = entities[2]["@id"]
    entities[2]["associatedAnnotationMethod"][0]["@id"] = entities[3]["@id"]
    rows = "file_path\tdataset\ttype\tsource_image\nimage.tif\thttps://example.org/dataset\thttp://bia/Image\t\n"
    assert not errors(profile_validate(entities, rows))


def test_relative_path_identifier_is_allowed(submission):
    entities, profile_validate = submission
    entities[2]["@id"] = "datasets/dataset"
    entities[0]["hasPart"][0]["@id"] = "datasets/dataset"
    rows = "file_path\tdataset\ttype\tsource_image\nimage.tif\tdatasets/dataset\thttp://bia/Image\t\n"
    assert not errors(profile_validate(entities, rows))


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
    "name", ["source image", "source_image", "associated_source_image", "input_image"]
)
def test_annotation_source_column_name_and_property(submission, name):
    entities, profile_validate = submission
    entities[-1]["columnName"] = name
    rows = f"filepath\tdataset\ttype\t{name}\nimage.tif\t#dataset\thttp://bia/Image\t\n"
    entities[6]["columnName"] = "filepath"
    assert not errors(profile_validate(entities, rows))
    entities[-1]["propertyUrl"] = "http://bia/sourceImageLabel"
    assert any(
        "annotation dataset requires" in msg.lower()
        for msg in errors(profile_validate(entities, rows))
    )


def test_filepath_first_column_uses_property_not_name(submission):
    entities, profile_validate = submission
    entities[6]["columnName"] = "path_to_file"
    rows = "path_to_file\tdataset\ttype\tsource_image\nimage.tif\t#dataset\thttp://bia/Image\t\n"
    assert not errors(profile_validate(entities, rows))
    rows = "dataset\tpath_to_file\ttype\tsource_image\n#dataset\timage.tif\thttp://bia/Image\t\n"
    assert any(
        "first file-list column" in issue
        for issue in errors(profile_validate(entities, rows))
    )


@pytest.fixture
def typical_profile_crate(tmp_path):

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
    by_id["_:col4"]["columnName"] = "input_image"
    by_id["_:col4"]["propertyUrl"] = "http://bia/associatedSourceImage"
    by_id["_:ts0"]["column"] = [
        ref for ref in by_id["_:ts0"]["column"] if ref["@id"] != "_:col6"
    ]
    data["@graph"] = [entity for entity in data["@graph"] if entity["@id"] != "_:col6"]
    path_column = next(
        entity
        for entity in data["@graph"]
        if entity.get("propertyUrl") == "http://bia/filePath"
    )
    path_column["columnName"] = "path_to_file"
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
    lines = (fixture / "file_list.tsv").read_text().splitlines()
    rows = [line.split("\t") for line in lines]
    annotation_column = rows[0].index("associated_annotation_method")
    for row in rows:
        row.pop(annotation_column)
    rows[0] = [
        name.replace("source_image_label", "input_image").replace(
            "file_path", "path_to_file"
        )
        for name in rows[0]
    ]
    (tmp_path / "file_list.tsv").write_text(
        "\n".join("\t".join(row) for row in rows) + "\n"
    )
    return tmp_path, data, by_id


def test_profile_preserves_base_findings(typical_profile_crate):
    from bia_ro_crate.validator import bia_roc_validation

    tmp_path, _, _ = typical_profile_crate
    default_report = bia_roc_validation(tmp_path, "report")
    result = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert set(result) == {"highest_error_level", "issues"}
    assert result["issues"]["ERROR"] == []
    for severity, issues in default_report["issues"].items():
        assert all(issue in result["issues"][severity] for issue in issues)


def test_source_reference_wrong_type_fails_base_and_profile(typical_profile_crate):
    from bia_ro_crate.validator import bia_roc_validation

    tmp_path, _, _ = typical_profile_crate
    path = tmp_path / "file_list.tsv"
    original = path.read_text()
    lines = original.splitlines()
    row = lines[1].split("\t")
    row[5] = row[4]  # Point to the annotation row, which is not a BIA Image.
    lines[1] = "\t".join(row)
    path.write_text("\n".join(lines) + "\n")
    for profile in (None, "bia-submission-v0"):
        result = bia_roc_validation(tmp_path, "report", profile=profile)
        assert any(
            "expected 'http://bia/Image'" in issue["message"]
            for issue in result["issues"]["ERROR"]
        )


def test_profile_requires_study_to_link_file_list_directly(typical_profile_crate):
    from bia_ro_crate.validator import bia_roc_validation

    tmp_path, data, by_id = typical_profile_crate
    by_id["./"]["hasPart"] = [
        ref for ref in by_id["./"]["hasPart"] if ref["@id"] != "file_list.tsv"
    ]
    by_id["#Imaging%20Dataset"]["hasPart"] = [{"@id": "file_list.tsv"}]
    (tmp_path / "ro-crate-metadata.json").write_text(json.dumps(data))
    base_report = bia_roc_validation(tmp_path, "report")
    assert not base_report["issues"]["ERROR"]
    profile_report = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert any(
        "Study hasPart must reference file_list.tsv" in issue["message"]
        for issue in profile_report["issues"]["ERROR"]
    )


def test_profile_reports_file_list_schema_errors(typical_profile_crate):
    from bia_ro_crate.validator import bia_roc_validation

    tmp_path, _, _ = typical_profile_crate
    path = tmp_path / "file_list.tsv"
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
