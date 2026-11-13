"""Additional BIA submission checks on a successfully parsed RO-Crate."""

from collections import Counter
from urllib.parse import urlsplit

import pandas as pd

from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.core.validation import Severity
from bia_ro_crate.core.validation.validation_error import ValidationError
from bia_ro_crate.models import ro_crate_models as models
from bia_ro_crate.models.linked_data.ontology_terms import BIA, SCHEMA


class SubmissionChecks:
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
        studies = list(self.by_type[models.Study].values())
        datasets = list(self.by_type[models.Dataset].values())
        if len(studies) != 1:
            self.issue(f"Expected exactly one BIA study, found {len(studies)}.")
        if not datasets:
            self.issue("Expected at least one BIA dataset.")

        for cls in (
            models.Dataset,
            models.SpecimenImagingPreparationProtocol,
            models.ImageAcquisitionProtocol,
            models.AnnotationMethod,
            models.SignalChannelInformation,
        ):
            for entity in self.by_type[cls].values():
                try:
                    parts = urlsplit(entity.id)
                    local = (
                        bool(entity.id)
                        and not entity.id.startswith("_:")
                        and not parts.scheme
                        and not parts.netloc
                    )
                except ValueError:
                    local = False
                if not local:
                    self.issue(
                        "Entity must have a relative IRI as its local identifier; absolute IRIs and blank-node identifiers are not allowed.",
                        entity,
                    )

        file_list = self.metadata.get_file_list_entity()
        if file_list.id != "file_list.tsv":
            self.issue(
                "BIA submission file list must be named file_list.tsv.", file_list
            )
        if not self.has_type(
            file_list, "http://schema.org/MediaObject"
        ) or not self.has_type(file_list, "http://www.w3.org/ns/csvw#Table"):
            self.issue("File list must also have types File and csvw:Table.", file_list)

        for study in studies:
            if not self.has_type(study, SCHEMA.Dataset):
                self.issue("Study must also have type Dataset.", study)
            self.check_fields(study, ("name", "description", "hasPart"))
            if str(study.license) not in (
                "https://creativecommons.org/publicdomain/zero/1.0/",
                "https://creativecommons.org/licenses/by/4.0/",
            ):
                self.issue("Study license must be CC0 1.0 or CC BY 4.0.", study)
            included = {ref.id for ref in study.hasPart}
            for entity in datasets + [file_list]:
                if entity.id not in included:
                    self.issue(f"Study hasPart must reference {entity.id}.", study)
            self.check_refs(study, "author", models.Contributor)
            self.check_refs(study, "relatedPublication", models.Publication)
            self.check_fields(
                study,
                (
                    "relatedPublication",
                    "acknowledgement",
                    "keywords",
                    "funding",
                    "seeAlso",
                ),
                Severity.WARNING,
            )

        for dataset in datasets:
            if not self.has_type(dataset, SCHEMA.Dataset):
                self.issue("BIA dataset must also have type Dataset.", dataset)
            self.check_fields(dataset, ("name",))
            imaging = (
                "associatedBiologicalEntity",
                "associatedSpecimenImagingPreparationProtocol",
                "associatedImageAcquisitionProtocol",
            )
            if not dataset.associatedAnnotationMethod and not all(
                getattr(dataset, field) for field in imaging
            ):
                self.issue(
                    "Dataset must reference an annotation method, or a biosample, preparation protocol and acquisition protocol.",
                    dataset,
                )
            for field, expected in (
                (imaging[0], models.BioSample),
                (imaging[1], models.SpecimenImagingPreparationProtocol),
                (imaging[2], models.ImageAcquisitionProtocol),
                ("associatedAnnotationMethod", models.AnnotationMethod),
            ):
                self.check_refs(dataset, field, expected)

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
        for sample in self.by_type[models.BioSample].values():
            self.check_refs(sample, "organismClassification", models.Taxon)
            self.check_refs(
                sample,
                "growthProtocol",
                (
                    models.Protocol,
                    models.AnnotationMethod,
                    models.ImageAcquisitionProtocol,
                    models.SpecimenImagingPreparationProtocol,
                ),
            )
        for protocol in self.by_type[
            models.SpecimenImagingPreparationProtocol
        ].values():
            self.check_refs(
                protocol, "signalChannelInformation", models.SignalChannelInformation
            )
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

    def check_file_list(self):
        file_list = self.file_list
        columns = {
            file_list.schema[col].columnName: file_list.schema[col]
            for col in file_list.data.columns
        }
        names = list(columns)
        if not names or names[0] not in ("filepath", "file_path"):
            self.issue("The first file-list column must be 'filepath' or 'file_path'.")
        elif columns[names[0]].propertyUrl != str(BIA.filePath):
            self.issue("The filepath column must have propertyUrl http://bia/filePath.")
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
                name in columns
                and columns[name].propertyUrl == str(BIA.associatedSourceImage)
                for name in ("source image", "source_image", "associated_source_image")
            ):
                self.issue(
                    "An annotation dataset requires a 'source image', 'source_image', or 'associated_source_image' column with propertyUrl http://bia/associatedSourceImage."
                )
        if not all(name in columns for name in expected):
            return
        datasets = file_list.data[columns["dataset"].id]
        types = file_list.data[columns["type"].id]
        dataset_rows, image_rows = Counter(), Counter()
        for row_number, (dataset, file_type) in enumerate(
            zip(datasets, types), start=2
        ):
            if not pd.isna(dataset):
                dataset_rows[dataset] += 1
            if pd.isna(file_type) or file_type not in (
                str(BIA.Image),
                str(BIA.AnnotationData),
                "http://bia/File",
            ):
                self.issue(
                    f"File-list row {row_number} has unsupported type '{'' if pd.isna(file_type) else file_type}'; expected http://bia/Image, http://bia/AnnotationData, or http://bia/File."
                )
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
