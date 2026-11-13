"""Additional checks for the versioned BIA submission profile.

The minimal parser remains the source of the existing validation behaviour.
These checks work on the input rather than requiring every entity to have
successfully constructed a Pydantic model.
"""

import csv
import json
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from pyld import jsonld

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.core.validation import Severity
from bia_ro_crate.core.validation.validation_error import ValidationError
from bia_ro_crate.models.linked_data.ontology_terms import BIA, CSVW, SCHEMA
from bia_ro_crate.validator.validation import (
    ValidationResponseMode,
    _log_issues,
    _report_issues,
)


def _values(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _references(value):
    return [
        item["@id"]
        for item in _values(value)
        if isinstance(item, dict) and isinstance(item.get("@id"), str)
    ]


def _present(value):
    return value is not None and value != "" and value != []


class SubmissionChecks:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.issues = []
        self.entities = []
        self.by_id = {}
        self.types = {}

    def issue(self, message, entity=None, severity=Severity.ERROR):
        self.issues.append(
            ValidationError(
                message=message,
                severity=severity,
                location_description=(
                    f"At ro-crate object with @id: {entity}"
                    if entity is not None
                    else None
                ),
            )
        )

    def objects_of_type(self, type_iri):
        return [
            entity
            for entity in self.entities
            if str(type_iri) in self.types.get(entity.get("@id"), set())
        ]

    def run(self):
        try:
            with (self.root / "ro-crate-metadata.json").open(
                encoding="utf-8"
            ) as stream:
                document = json.load(stream)
            entities = document["@graph"]
            if not isinstance(entities, list):
                return self.issues
            # Preserve the association between source IDs and expanded types,
            # including IDs that the context expands as compact IRIs.
            marker = f"urn:bia-validation:source-index:{uuid4()}"
            indexed = [
                {**entity, marker: str(index)} if isinstance(entity, dict) else entity
                for index, entity in enumerate(entities)
            ]
            expanded = jsonld.expand({**document, "@graph": indexed})
        except (OSError, ValueError, KeyError, TypeError, jsonld.JsonLdError):
            # The minimal validator is responsible for reporting input errors.
            return self.issues
        self.entities = [entity for entity in entities if isinstance(entity, dict)]
        self.by_id = {
            entity.get("@id"): entity
            for entity in self.entities
            if isinstance(entity.get("@id"), str)
        }
        self.types = {}
        for node in expanded:
            if not isinstance(node, dict):
                continue
            values = node.get(marker, [])
            if not values:
                continue
            index = int(values[0]["@value"])
            source_id = entities[index].get("@id")
            self.types[source_id] = set(node.get("@type", []))
        self.check_metadata()
        self.check_file_list()
        return self.issues

    def required(self, entity, fields):
        for field in fields:
            if not _present(entity.get(field)):
                self.issue(
                    f"Required property '{field}' is missing or empty.",
                    entity.get("@id"),
                )

    def recommended(self, entity, fields):
        for field in fields:
            if not _present(entity.get(field)):
                self.issue(
                    f"Recommended property '{field}' is missing or empty.",
                    entity.get("@id"),
                    Severity.WARNING,
                )

    def check_references(self, entity, field, expected_type):
        self.check_reference_types(entity, field, (expected_type,))

    def check_reference_types(self, entity, field, expected_types):
        expected = {str(item) for item in expected_types}
        for ref in _references(entity.get(field)):
            if ref not in self.by_id:
                self.issue(
                    f"Property '{field}' references an entity that does not exist: {ref}.",
                    entity.get("@id"),
                )
            elif not (expected & self.types.get(ref, set())):
                self.issue(
                    f"Property '{field}' references {ref}, which must have type {' or '.join(sorted(expected))}.",
                    entity.get("@id"),
                )

    def check_metadata(self):
        studies = self.objects_of_type(BIA.Study)
        datasets = self.objects_of_type(BIA.Dataset)
        file_lists = self.objects_of_type(BIA.FileList)
        if len(studies) != 1:
            self.issue(f"Expected exactly one BIA study, found {len(studies)}.")
        if not datasets:
            self.issue("Expected at least one BIA dataset.")
        if len(file_lists) != 1:
            self.issue(f"Expected exactly one BIA file list, found {len(file_lists)}.")

        for entity_type in (
            BIA.Dataset,
            BIA.SpecimenImagingPreparationProtocol,
            BIA.ImageAcquisitionProtocol,
            BIA.AnnotationMethod,
            BIA.SignalChannel,
        ):
            for entity in self.objects_of_type(entity_type):
                entity_id = entity.get("@id")
                if isinstance(entity_id, str):
                    try:
                        parts = urlsplit(entity_id)
                        local = (
                            bool(entity_id)
                            and not entity_id.startswith("_:")
                            and not parts.scheme
                            and not parts.netloc
                        )
                    except ValueError:
                        local = False
                    if not local:
                        self.issue(
                            "Entity must have a relative IRI as its local identifier; absolute IRIs and blank-node identifiers are not allowed.",
                            entity_id,
                        )

        for study in studies:
            sid = study.get("@id")
            if sid != "./":
                self.issue("Study @id must be './'.", sid)
            if str(SCHEMA.Dataset) not in self.types.get(sid, set()):
                self.issue("Study must also have type Dataset.", sid)
            self.required(
                study,
                (
                    "name",
                    "description",
                    "license",
                    "hasPart",
                    "author",
                ),
            )
            if _present(study.get("license")) and study["license"] not in (
                "https://creativecommons.org/publicdomain/zero/1.0/",
                "https://creativecommons.org/licenses/by/4.0/",
            ):
                self.issue("Study license must be CC0 1.0 or CC BY 4.0.", sid)
            included = set(_references(study.get("hasPart")))
            for item in datasets + file_lists:
                if item.get("@id") not in included:
                    self.issue(f"Study hasPart must reference {item.get('@id')}.", sid)
            self.check_references(study, "author", BIA.Contributor)
            self.check_references(study, "relatedPublication", BIA.Publication)
            self.recommended(
                study,
                (
                    "relatedPublication",
                    "acknowledgement",
                    "keywords",
                    "funding",
                    "seeAlso",
                ),
            )

        for dataset in datasets:
            did = dataset.get("@id")
            if str(SCHEMA.Dataset) not in self.types.get(did, set()):
                self.issue("BIA dataset must also have type Dataset.", did)
            self.required(dataset, ("name",))
            imaging = (
                "associatedBiologicalEntity",
                "associatedSpecimenImagingPreparationProtocol",
                "associatedImageAcquisitionProtocol",
            )
            if not _present(dataset.get("associatedAnnotationMethod")) and not all(
                _present(dataset.get(field)) for field in imaging
            ):
                self.issue(
                    "Dataset must reference an annotation method, or a biosample, preparation protocol and acquisition protocol.",
                    did,
                )
            for field, expected in (
                (imaging[0], BIA.BioSample),
                (imaging[1], BIA.SpecimenImagingPreparationProtocol),
                (imaging[2], BIA.ImageAcquisitionProtocol),
                ("associatedAnnotationMethod", BIA.AnnotationMethod),
            ):
                self.check_references(dataset, field, expected)

        requirements = (
            (BIA.Publication, ("name",), ("doi", "pubmedId", "authorNames")),
            (
                BIA.BioSample,
                ("name", "description", "organismClassification"),
                (
                    "experimentalVariableDescription",
                    "extrinsicVariableDescription",
                    "intrinsicVariableDescription",
                    "growthProtocol",
                ),
            ),
            (BIA.Taxon, ("scientificName",), ()),
            (
                BIA.SpecimenImagingPreparationProtocol,
                ("name", "description"),
                ("signalChannelInformation",),
            ),
            (
                BIA.SignalChannel,
                (),
                (
                    "channelBiologicalEntity",
                    "signalContrastMechanismDescription",
                    "channelContentDescription",
                ),
            ),
            (
                BIA.ImageAcquisitionProtocol,
                (
                    "name",
                    "description",
                    "imagingInstrumentDescription",
                    "imagingMethodName",
                    "fbbiId",
                ),
                (),
            ),
            (
                BIA.AnnotationMethod,
                ("name", "description", "methodType"),
                (
                    "annotationCriteria",
                    "annotationCoverage",
                    "annotationSourceIndicator",
                ),
            ),
        )
        for entity_type, required, recommended in requirements:
            for entity in self.objects_of_type(entity_type):
                self.required(entity, required)
                self.recommended(entity, recommended)
        for entity in self.objects_of_type(BIA.BioSample):
            self.check_references(entity, "organismClassification", BIA.Taxon)
            # The bundled ontology declares these classes as Protocol subclasses.
            self.check_reference_types(
                entity,
                "growthProtocol",
                (
                    BIA.Protocol,
                    BIA.AnnotationMethod,
                    BIA.ImageAcquisitionProtocol,
                    BIA.SpecimenImagingPreparationProtocol,
                ),
            )
        for entity in self.objects_of_type(BIA.SpecimenImagingPreparationProtocol):
            self.check_references(entity, "signalChannelInformation", BIA.SignalChannel)
        for entity in self.objects_of_type(BIA.Contributor):
            types = self.types.get(entity.get("@id"), set())
            if not ({str(SCHEMA.Person), str(SCHEMA.Organization)} & types):
                self.issue(
                    "Contributor must also have type Person or Organization.",
                    entity.get("@id"),
                )
            if str(SCHEMA.Person) in types:
                self.recommended(entity, ("memberOf",))
            # bia:Affiliation is a subclass of schema:Organization.
            self.check_reference_types(
                entity, "memberOf", (SCHEMA.Organization, BIA.Affiliation)
            )
        for entity in file_lists:
            if entity.get("@id") != "file_list.tsv":
                self.issue(
                    "BIA submission file list must be named file_list.tsv.",
                    entity.get("@id"),
                )
            if not {
                "http://schema.org/MediaObject",
                "http://www.w3.org/ns/csvw#Table",
            } <= self.types.get(entity.get("@id"), set()):
                # RO-Crate's File is schema:MediaObject in its context.
                self.issue(
                    "File list must also have types File and csvw:Table.",
                    entity.get("@id"),
                )

    def check_file_list(self):
        file_lists = self.objects_of_type(BIA.FileList)
        if len(file_lists) != 1:
            return
        file_list = file_lists[0]
        schema_refs = _references(file_list.get("tableSchema"))
        schema = self.by_id.get(schema_refs[0]) if len(schema_refs) == 1 else None
        if not schema:
            return
        columns = [self.by_id.get(ref) for ref in _references(schema.get("column"))]
        columns = [
            column
            for column in columns
            if column and str(CSVW.Column) in self.types.get(column.get("@id"), set())
        ]
        defined = Counter(column.get("columnName") for column in columns)
        columns_by_name = {column.get("columnName"): column for column in columns}
        path = self.root / unquote(str(file_list.get("@id", "")))
        try:
            with path.open(encoding="utf-8", newline="") as stream:
                reader = csv.reader(stream, delimiter="\t", strict=True)
                headers = next(reader, [])
                for header in headers:
                    if not defined[header]:
                        self.issue(
                            f"File-list column '{header}' must have a csvw:Column definition in its table schema."
                        )
                if not headers or headers[0] not in ("filepath", "file_path"):
                    self.issue(
                        "The first file-list column must be 'filepath' or 'file_path'."
                    )
                elif columns_by_name.get(headers[0], {}).get("propertyUrl") != str(
                    BIA.filePath
                ):
                    self.issue(
                        "The filepath column must have propertyUrl http://bia/filePath."
                    )
                for header in ("dataset", "type"):
                    if header not in headers:
                        self.issue(f"File list must contain a '{header}' column.")
                expected_properties = {
                    "dataset": str(SCHEMA.isPartOf),
                    "type": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
                }
                for header, property_iri in expected_properties.items():
                    if (
                        header in headers
                        and columns_by_name.get(header, {}).get("propertyUrl")
                        != property_iri
                    ):
                        self.issue(
                            f"File-list column '{header}' must have propertyUrl {property_iri}."
                        )
                if any(
                    _present(dataset.get("associatedAnnotationMethod"))
                    for dataset in self.objects_of_type(BIA.Dataset)
                ):
                    source_names = (
                        "source image",
                        "source_image",
                        "associated_source_image",
                    )
                    if not any(
                        name in headers
                        and columns_by_name.get(name, {}).get("propertyUrl")
                        == str(BIA.associatedSourceImage)
                        for name in source_names
                    ):
                        self.issue(
                            "An annotation dataset requires a 'source image', 'source_image', or 'associated_source_image' column with propertyUrl http://bia/associatedSourceImage."
                        )
                if "dataset" not in headers or "type" not in headers:
                    return
                dataset_index, type_index = headers.index("dataset"), headers.index(
                    "type"
                )
                dataset_rows = Counter()
                image_rows = Counter()
                for row in reader:
                    if len(row) <= max(dataset_index, type_index):
                        self.issue(
                            f"File-list row {reader.line_num} has no dataset or type value."
                        )
                        continue
                    dataset_rows[row[dataset_index]] += 1
                    if row[type_index] not in (
                        str(BIA.Image),
                        str(BIA.AnnotationData),
                        "http://bia/File",
                    ):
                        self.issue(
                            f"File-list row {reader.line_num} has unsupported type '{row[type_index]}'; expected http://bia/Image, http://bia/AnnotationData, or http://bia/File."
                        )
                    if row[type_index] == str(BIA.Image):
                        image_rows[row[dataset_index]] += 1
                for dataset in self.objects_of_type(BIA.Dataset):
                    did = dataset.get("@id")
                    if not dataset_rows[did]:
                        self.issue("Dataset must have at least one file-list row.", did)
                    if (
                        _present(dataset.get("associatedImageAcquisitionProtocol"))
                        and not image_rows[did]
                    ):
                        self.issue(
                            "Dataset with an acquisition protocol must have at least one image in the file list.",
                            did,
                        )
        except (OSError, UnicodeError, csv.Error):
            return


def validate(root: Path, mode: ValidationResponseMode):
    parser = ROCrateParser(root)
    failed = False
    parsing_issue = None
    try:
        parser.parse()
        parser.result
    except ExceptionGroup:
        failed = True
    except (OSError, ValueError, KeyError, UnicodeError, csv.Error) as exc:
        failed = True
        parsing_issue = ValidationError(
            message=f"Unable to parse the submission: {exc}", severity=Severity.ERROR
        )
    issues = parser.issues + SubmissionChecks(root).run()
    if parsing_issue is not None:
        issues.append(parsing_issue)
    result = SimpleNamespace(issues=issues)
    _log_issues(result)
    if mode == ValidationResponseMode.report:
        return _report_issues(result)
    if failed or any(issue.severity >= Severity.ERROR for issue in issues):
        raise SystemExit(1)
