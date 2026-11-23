"""Additional BIA submission checks on a successfully parsed RO-Crate."""

from collections import Counter

import pandas as pd

from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.core.validation import Severity
from bia_ro_crate.core.validation.validation_error import ValidationError
from bia_ro_crate.models import ro_crate_models as models
from bia_ro_crate.models.linked_data.ontology_terms import BIA, SCHEMA


class SubmissionChecks:
    # Ingest overrides these dataset associations with file-list values.
    # Source images are deliberately excluded from this profile check for now.
    ASSOCIATION_FIELDS = {
        str(BIA.associatedBiologicalEntity): "associatedBiologicalEntity",
        str(
            BIA.associatedImagingPreparationProtocol
        ): "associatedSpecimenImagingPreparationProtocol",
        str(BIA.associatedProtocol): "associatedProtocol",
        str(BIA.associatedCreationProcess): "associatedCreationProcess"
    }
    REQUIRED_IF_DATASET_HAS_ASSOCIATION = {
        str(BIA.associatedBiologicalEntity),
        str(BIA.associatedImagingPreparationProtocol)
    }

    def __init__(self, submission: BIASubmissionMetadata):
        self.metadata = submission.metadata
        self.file_list = submission.file_list
        self.objects = self.metadata.get_object_lookup()
        self.by_type = self.metadata.get_objects_by_type()
        self.issues: list[ValidationError] = []

    def issue(self, message, entity=None, severity=Severity.ERROR):
        self.issues.append(
            ValidationError(
                message=message,
                severity=severity,
                location_description=(
                    f"At ro-crate object with @id: {entity.id}" if entity else None
                ),
            )
        )

    def check_fields(self, entity, fields, severity=Severity.ERROR):
        for field in fields:
            if getattr(entity, field) in (None, "", []):
                label = "Required" if severity == Severity.ERROR else "Recommended"
                self.issue(
                    f"{label} property '{field}' is missing or empty.", entity, severity
                )

    def has_type(self, entity, expected):
        context = self.metadata.get_context()
        for value in [entity.type] if isinstance(entity.type, str) else entity.type:
            term = context.terms.get(value)
            prefix, separator, suffix = value.partition(":")
            expanded = (
                str(term.full_uri)
                if term
                else (
                    context.prefixes[prefix] + suffix
                    if separator and prefix in context.prefixes
                    else value
                )
            )
            if expanded == str(expected):
                return True
        return False

    def check_refs(self, entity, field, expected_types):
        refs = getattr(entity, field)
        for ref in refs if isinstance(refs, list) else [refs] if refs else []:
            target = self.objects.get(ref.id)
            if not isinstance(target, expected_types):
                types = (
                    expected_types
                    if isinstance(expected_types, tuple)
                    else (expected_types,)
                )
                expected = " or ".join(
                    sorted(str(model.get_model_type()) for model in types)
                )
                self.issue(
                    f"Property '{field}' references {ref.id}, which must have type {expected}.",
                    entity,
                )

    def run(self):
        self.check_metadata()
        self.check_file_list()
        return self.issues

    def check_metadata(self):
        self.check_study_and_dataset_counts()
        self.check_identifiers()
        self.check_file_list_metadata()
        self.check_studies()
        self.check_datasets()
        self.check_entity_fields()
        self.check_entity_references()
        self.check_contributors()

    def check_study_and_dataset_counts(self):
        studies = list(self.by_type[models.Study].values())
        datasets = list(self.by_type[models.Dataset].values())
        if len(studies) != 1:
            self.issue(f"Expected exactly one BIA study, found {len(studies)}.")
        if not datasets:
            self.issue("Expected at least one BIA dataset.")

    def check_identifiers(self):
        for cls in (
            models.Dataset,
            models.SpecimenImagingPreparationProtocol,
            models.ImageAcquisitionProtocol,
            models.AnnotationMethod,
            models.SignalChannelInformation,
        ):
            for entity in self.by_type[cls].values():
                if entity.id.startswith("_:"):
                    self.issue(
                        "Entity must not have a blank-node identifier.",
                        entity,
                    )

    def check_file_list_metadata(self):
        file_list = self.metadata.get_file_list_entity()
        if file_list.id != "file_list.tsv":
            self.issue(
                "BIA submission file list must be named file_list.tsv.", file_list
            )
        if not self.has_type(
            file_list, "http://schema.org/MediaObject"
        ) or not self.has_type(file_list, "http://www.w3.org/ns/csvw#Table"):
            self.issue("File list must also have types File and csvw:Table.", file_list)

    def check_studies(self):
        studies = self.by_type[models.Study].values()
        dataset_ids = self.by_type[models.Dataset]
        file_list = self.metadata.get_file_list_entity()
        for study in studies:
            if str(study.license) not in (
                "https://creativecommons.org/publicdomain/zero/1.0/",
                "https://creativecommons.org/licenses/by/4.0/",
            ):
                self.issue("Study license must be CC0 1.0 or CC BY 4.0.", study)
            included = {ref.id for ref in study.hasPart}
            if file_list.id not in included:
                self.issue(f"Study hasPart must reference {file_list.id}.", study)
            for dataset_id in dataset_ids:
                if dataset_id not in included:
                    self.issue(f"Study hasPart must reference {dataset_id}.", study)

    def check_datasets(self):
        datasets = list(self.by_type[models.Dataset].values())
        imaging = (
            "associatedBiologicalEntity",
            "associatedSpecimenImagingPreparationProtocol",
            "associatedImageAcquisitionProtocol",
        )

        def has_primary_associations(dataset):
            return bool(dataset.associatedAnnotationMethod) or all(
                getattr(dataset, field) for field in imaging
            )

        if datasets and not any(
            has_primary_associations(dataset) for dataset in datasets
        ):
            self.issue(
                "At least one dataset must reference an annotation method, or a biosample, preparation protocol and acquisition protocol."
            )
        for dataset in datasets:
            if not self.has_type(dataset, SCHEMA.Dataset):
                self.issue("BIA dataset must also have type Dataset.", dataset)
            self.check_fields(dataset, ("name",))
            if not has_primary_associations(dataset) and not dataset.associatedProtocol:
                self.issue(
                    "Dataset must reference a protocol or an annotation method, or a biosample, preparation protocol and acquisition protocol.",
                    dataset,
                )
            for field, expected in (
                (imaging[0], models.BioSample),
                (imaging[1], models.SpecimenImagingPreparationProtocol),
                (imaging[2], models.ImageAcquisitionProtocol),
                ("associatedAnnotationMethod", models.AnnotationMethod),
                ("associatedProtocol",models.Protocol),
            ):
                self.check_refs(dataset, field, expected)

    def check_entity_fields(self):
        requirements = (
            (models.Publication, ("name",), ("doi", "pubmedId", "authorNames")),
            (
                models.BioSample,
                ("name", "description", "organismClassification"),
                (
                    "experimentalVariableDescription",
                    "extrinsicVariableDescription",
                    "intrinsicVariableDescription",
                    "growthProtocol",
                ),
            ),
            (models.Taxon, ("scientificName",), ()),
            (
                models.SpecimenImagingPreparationProtocol,
                ("name", "description"),
                ("signalChannelInformation",),
            ),
            (
                models.SignalChannelInformation,
                (),
                (
                    "channelBiologicalEntity",
                    "signalContrastMechanismDescription",
                    "channelContentDescription",
                ),
            ),
            (
                models.ImageAcquisitionProtocol,
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
                models.AnnotationMethod,
                ("name", "description", "methodType"),
                (
                    "annotationCriteria",
                    "annotationCoverage",
                    "annotationSourceIndicator",
                ),
            ),
        )
        for cls, required, recommended in requirements:
            for entity in self.by_type[cls].values():
                self.check_fields(entity, required)
                self.check_fields(entity, recommended, Severity.WARNING)

    def check_entity_references(self):
        for sample in self.by_type[models.BioSample].values():
            self.check_refs(sample, "organismClassification", models.Taxon)
            self.check_refs(
                sample,
                "growthProtocol",
                models.Protocol,
            )
        for protocol in self.by_type[
            models.SpecimenImagingPreparationProtocol
        ].values():
            self.check_refs(
                protocol, "signalChannelInformation", models.SignalChannelInformation
            )

    def check_contributors(self):
        for contributor in self.by_type[models.Contributor].values():
            person = self.has_type(contributor, SCHEMA.Person)
            if not person and not self.has_type(contributor, SCHEMA.Organization):
                self.issue(
                    "Contributor must also have type Person or Organization.",
                    contributor,
                )
            if person:
                self.check_fields(contributor, ("memberOf",), Severity.WARNING)
            for ref in contributor.memberOf:
                target = self.objects.get(ref.id)
                if target is None or not (
                    isinstance(target, models.Affiliation)
                    or self.has_type(target, SCHEMA.Organization)
                ):
                    self.issue(
                        f"Property 'memberOf' references {ref.id}, which must have type {SCHEMA.Organization} or {BIA.Affiliation}.",
                        contributor,
                    )

    @staticmethod
    def association_values(value):
        if isinstance(value, list):
            return [str(item) for item in value if item]
        if not isinstance(value, str):
            return [] if pd.isna(value) else [str(value)]
        value = value.strip()
        if not value:
            return []
        if value.startswith("["):
            return [
                item.strip().strip("\"'")
                for item in value.strip("[] ").split(",")
                if item.strip()
            ]
        return [value]

    def check_file_list_associations(self, columns):
        dataset_column = columns["dataset"].id
        association_columns = [
            (column, self.ASSOCIATION_FIELDS[column.propertyUrl])
            for column in columns.values()
            if column.propertyUrl in self.ASSOCIATION_FIELDS
        ]
        if not association_columns:
            return
        for row_number, (_, row) in enumerate(self.file_list.data.iterrows(), start=2):
            dataset = self.by_type[models.Dataset].get(row[dataset_column])
            if dataset is None:
                continue
            for column, field in association_columns:
                refs = getattr(dataset, field)
                allowed = (
                    {ref.id for ref in refs}
                    if isinstance(refs, list)
                    else {refs.id} if refs else set()
                )
                values = self.association_values(row[column.id])
                if (
                    column.propertyUrl in self.REQUIRED_IF_DATASET_HAS_ASSOCIATION
                    and allowed
                    and not values
                ):
                    self.issue(
                        f"File-list row {row_number} must provide {column.propertyUrl} because dataset {dataset.id} has that association."
                    )
                for value in values:
                    if value not in allowed:
                        self.issue(
                            f"File-list row {row_number} references {value} via {column.propertyUrl}, but dataset {dataset.id} does not include that association."
                        )

    def check_file_list(self):
        file_list = self.file_list
        columns = {
            file_list.schema[col].columnName: file_list.schema[col]
            for col in file_list.data.columns
        }
        names = list(columns)
        if not names or columns[names[0]].propertyUrl != str(BIA.filePath):
            self.issue(
                "The first file-list column must have propertyUrl http://bia/filePath."
            )
        for column in columns.values():
            if column.propertyUrl in (
                str(BIA.associatedImageAcquisitionProtocol),
                str(BIA.associatedAnnotationMethod),
                str(BIA.associatedSubject)
            ):
                self.issue(
                    f"File-list column '{column.columnName}' must not use propertyUrl {column.propertyUrl}; specify the association on the dataset."
                )
        expected = {
            "dataset": str(SCHEMA.isPartOf),
            "type": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type",
        }
        for name, property_iri in expected.items():
            if name not in columns:
                self.issue(f"File list must contain a '{name}' column.")
            elif columns[name].propertyUrl != property_iri:
                self.issue(
                    f"File-list column '{name}' must have propertyUrl {property_iri}."
                )
        if any(
            dataset.associatedAnnotationMethod
            for dataset in self.by_type[models.Dataset].values()
        ):
            if not any(
                column.propertyUrl == str(BIA.associatedSourceImage)
                for column in columns.values()
            ):
                self.issue(
                    "An annotation dataset requires a file-list column with propertyUrl http://bia/associatedSourceImage."
                )
        if not all(name in columns for name in expected):
            return
        for column in columns.values():
            if column.propertyUrl == str(SCHEMA.name):
                labels_by_dataset = {}
                for label, dataset in zip(
                    file_list.data[column.id], file_list.data[columns["dataset"].id]
                ):
                    if (
                        pd.isna(label)
                        or label == ""
                        or pd.isna(dataset)
                        or dataset == ""
                    ):
                        continue
                    labels_by_dataset.setdefault(label, set()).add(dataset)
                for label, datasets in labels_by_dataset.items():
                    if len(datasets) > 1:
                        self.issue(
                            f"File-list label '{label}' must not be shared across datasets."
                        )
        self.check_file_list_associations(columns)
        datasets = file_list.data[columns["dataset"].id]
        types = file_list.data[columns["type"].id]
        dataset_rows, image_rows = Counter(), Counter()
        for dataset, file_type in zip(datasets, types):
            if not pd.isna(dataset):
                dataset_rows[dataset] += 1
            if (
                not pd.isna(file_type)
                and file_type == str(BIA.Image)
                and not pd.isna(dataset)
            ):
                image_rows[dataset] += 1
        for dataset in self.by_type[models.Dataset].values():
            if not dataset_rows[dataset.id]:
                self.issue("Dataset must have at least one file-list row.", dataset)
            if (
                dataset.associatedImageAcquisitionProtocol
                and not image_rows[dataset.id]
            ):
                self.issue(
                    "Dataset with an acquisition protocol must have at least one image in the file list.",
                    dataset,
                )
