import json
from importlib.resources import files
from typing import Any

import pandas as pd

from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.core.validation.severity import Severity
from bia_ro_crate.core.validation.validation_error import ValidationError


class BIASubmissionProfileValidator:
    """Validate the BIA submission application profile bundled with the package."""

    PROFILE_RESOURCE = "profiles/bia-submission-ro-crate-profile.json"
    MODEL_DATASET_TYPES = {
        "rembiMetadataModel": "bia:RembiDataset",
        "mifaMetadataModel": "bia:MifaDataset",
    }

    def __init__(self, profile: dict[str, Any] | None = None) -> None:
        self.profile = profile or self._load_profile()

    def validate(self, submission: BIASubmissionMetadata) -> list[ValidationError]:
        issues = self._validate_requirements(
            submission, self.profile["submissionRequirements"]
        )

        for model_name, dataset_type in self.MODEL_DATASET_TYPES.items():
            if self._has_entity_with_type(submission, dataset_type):
                requirements = self.profile[model_name]["requirements"]
                issues.extend(self._validate_requirements(submission, requirements))

        return issues

    @classmethod
    def _load_profile(cls) -> dict[str, Any]:
        profile_resource = files("bia_ro_crate.validator").joinpath(
            cls.PROFILE_RESOURCE
        )
        return json.loads(profile_resource.read_text(encoding="utf-8"))

    def _validate_requirements(
        self,
        submission: BIASubmissionMetadata,
        requirements: list[dict[str, Any]],
    ) -> list[ValidationError]:
        issues: list[ValidationError] = []
        for requirement in requirements:
            entities = self._matching_entities(submission, requirement["target"])
            requirement_id = requirement["id"]

            if "minimumCount" in requirement:
                minimum_count = requirement["minimumCount"]
                if len(entities) < minimum_count:
                    issues.append(
                        self._issue(
                            requirement_id,
                            f"Expected at least {minimum_count} matching entity, found {len(entities)}.",
                        )
                    )

            if "requireTypes" in requirement:
                expected_types = set(requirement["requireTypes"])
                if not entities or not any(
                    expected_types <= self._entity_types(entity) for entity in entities
                ):
                    issues.append(
                        self._issue(
                            requirement_id,
                            "Expected an entity with types: "
                            f"{', '.join(requirement['requireTypes'])}.",
                        )
                    )

            if "requireAtLeastOneType" in requirement:
                required_types = set(requirement["requireAtLeastOneType"])
                if not any(
                    self._entity_types(entity) & required_types for entity in entities
                ):
                    issues.append(
                        self._issue(
                            requirement_id,
                            "Expected at least one matching entity with one of: "
                            f"{', '.join(requirement['requireAtLeastOneType'])}.",
                        )
                    )

            if "requiredProperties" in requirement:
                required_properties = requirement["requiredProperties"]
                valid_entities = [
                    entity
                    for entity in entities
                    if all(
                        self._property_is_present(entity, property_name)
                        for property_name in required_properties
                    )
                ]
                required_count = requirement.get("minimumCount", len(entities))
                if len(valid_entities) < required_count:
                    missing = self._missing_properties(entities, required_properties)
                    issues.append(
                        self._issue(
                            requirement_id,
                            "Expected at least "
                            f"{required_count} matching entity with required properties "
                            f"{', '.join(required_properties)}; found {len(valid_entities)}. "
                            f"Missing properties: {', '.join(missing)}.",
                        )
                    )

            # if "recommendedProperties" in requirement:
            #     issues.extend(
            #         self._validate_recommended_properties(
            #             entities, requirement_id, requirement["recommendedProperties"]
            #         )
            #     )

            if "requiredPropertyReferences" in requirement:
                issues.extend(
                    self._validate_required_property_references(
                        submission,
                        entities,
                        requirement_id,
                        requirement["requiredPropertyReferences"],
                        requirement.get("minimumCount", len(entities)),
                    )
                )

            if "requiredColumn" in requirement:
                issues.extend(
                    self._validate_required_column(
                        submission, requirement_id, requirement["requiredColumn"]
                    )
                )

            if "requiredRow" in requirement:
                issues.extend(
                    self._validate_required_row(
                        submission, requirement_id, requirement["requiredRow"]
                    )
                )

        return issues

    @staticmethod
    def _matching_entities(
        submission: BIASubmissionMetadata, target: dict[str, str]
    ) -> list[object]:
        objects = submission.metadata.get_objects()
        if "@id" in target:
            entity = submission.metadata.get_object(target["@id"])
            return [entity] if entity is not None else []

        expected_type = BIASubmissionProfileValidator._normalise_identifier(
            target["@type"]
        )
        return [
            entity
            for entity in objects
            if expected_type in BIASubmissionProfileValidator._entity_types(entity)
        ]

    @staticmethod
    def _has_entity_with_type(
        submission: BIASubmissionMetadata, expected_type: str
    ) -> bool:
        return any(
            BIASubmissionProfileValidator._normalise_identifier(expected_type)
            in BIASubmissionProfileValidator._entity_types(entity)
            for entity in submission.metadata.get_objects()
        )

    @staticmethod
    def _entity_types(entity: object) -> set[str]:
        entity_type = getattr(entity, "type")
        entity_types = entity_type if isinstance(entity_type, list) else [entity_type]
        return {
            BIASubmissionProfileValidator._normalise_identifier(value)
            for value in entity_types
        }

    @staticmethod
    def _normalise_identifier(value: object) -> str:
        identifier = str(value)
        for prefix in ("http://bia/", "https://bia/"):
            if identifier.startswith(prefix):
                return "bia:" + identifier.removeprefix(prefix)
        for prefix in ("http://schema.org/", "https://schema.org/"):
            if identifier.startswith(prefix):
                return identifier.removeprefix(prefix)
        return identifier

    @staticmethod
    def _property_is_present(entity: object, property_name: str) -> bool:
        value = getattr(entity, property_name, None)
        if value is None:
            return False
        if isinstance(value, (str, list, tuple, set, dict)):
            return bool(value)
        return True

    @classmethod
    def _missing_properties(
        cls, entities: list[object], required_properties: list[str]
    ) -> list[str]:
        missing_properties = {
            property_name
            for entity in entities
            for property_name in required_properties
            if not cls._property_is_present(entity, property_name)
        }
        return sorted(missing_properties)

    """ def _validate_recommended_properties(
        self,
        entities: list[object],
        requirement_id: str,
        recommended_properties: list[str],
    ) -> list[ValidationError]:
        missing_by_entity = {
            str(getattr(entity, "id")): [
                property_name
                for property_name in recommended_properties
                if not self._property_is_present(entity, property_name)
            ]
            for entity in entities
        }
        missing_by_entity = {
            entity_id: missing
            for entity_id, missing in missing_by_entity.items()
            if missing
        }
        if not missing_by_entity:
            return []

        missing_description = "; ".join(
            f"{entity_id}: {', '.join(missing)}"
            for entity_id, missing in sorted(missing_by_entity.items())
        )
        return [
            self._issue(
                requirement_id,
                f"Recommended properties are absent: {missing_description}.",
                severity=Severity.WARNING,
            )
        ]
 """
    def _validate_required_property_references(
        self,
        submission: BIASubmissionMetadata,
        entities: list[object],
        requirement_id: str,
        required_property_references: dict[str, dict[str, Any]],
        required_entity_count: int,
    ) -> list[ValidationError]:
        valid_entities = [
            entity
            for entity in entities
            if all(
                self._has_required_property_references(
                    submission, entity, property_name, reference_requirement
                )
                for property_name, reference_requirement in required_property_references.items()
            )
        ]
        if len(valid_entities) >= required_entity_count:
            return []

        expected_references = ", ".join(
            f"{property_name} -> {reference_requirement['targetType']} "
            f"(minimum {reference_requirement.get('minimumCount', 1)})"
            for property_name, reference_requirement in required_property_references.items()
        )
        return [
            self._issue(
                requirement_id,
                "Expected at least "
                f"{required_entity_count} matching entity with property references: "
                f"{expected_references}; found {len(valid_entities)}.",
            )
        ]

    def _has_required_property_references(
        self,
        submission: BIASubmissionMetadata,
        entity: object,
        property_name: str,
        reference_requirement: dict[str, Any],
    ) -> bool:
        value = getattr(entity, property_name, None)
        references = value if isinstance(value, list) else [value]
        target_type = self._normalise_identifier(reference_requirement["targetType"])
        valid_references = [
            reference
            for reference in references
            if self._reference_has_type(submission, reference, target_type)
        ]
        return len(valid_references) >= reference_requirement.get("minimumCount", 1)

    def _reference_has_type(
        self,
        submission: BIASubmissionMetadata,
        reference: object,
        target_type: str,
    ) -> bool:
        reference_id = getattr(reference, "id", None)
        if reference_id is None:
            return False
        referenced_entity = submission.metadata.get_object(reference_id)
        return referenced_entity is not None and target_type in self._entity_types(
            referenced_entity
        )

    def _validate_required_column(
        self,
        submission: BIASubmissionMetadata,
        requirement_id: str,
        required_column: dict[str, str],
    ) -> list[ValidationError]:
        expected_name = required_column["columnName"]
        expected_property = self._normalise_identifier(required_column["propertyUrl"])
        has_matching_column = any(
            column.columnName == expected_name
            and self._normalise_identifier(column.propertyUrl) == expected_property
            for column in submission.file_list.schema.values()
        )
        if has_matching_column:
            return []

        return [
            self._issue(
                requirement_id,
                "Expected file-list column "
                f"'{expected_name}' with propertyUrl '{required_column['propertyUrl']}'.",
            )
        ]

    def _validate_required_row(
        self,
        submission: BIASubmissionMetadata,
        requirement_id: str,
        required_row: dict[str, Any],
    ) -> list[ValidationError]:
        expected_name = required_row["columnName"]
        type_column = next(
            (
                column
                for column in submission.file_list.schema.values()
                if column.columnName == expected_name
            ),
            None,
        )
        if type_column is None:
            return [
                self._issue(
                    requirement_id,
                    f"Expected file-list column '{expected_name}' for required row check.",
                )
            ]

        accepted_values = {
            self._normalise_identifier(value)
            for value in required_row["acceptedValues"]
        }
        has_required_row = any(
            self._normalise_identifier(value) in accepted_values
            for value in submission.file_list.data[type_column.id]
            if not pd.isna(value)
        )
        if has_required_row:
            return []

        return [
            self._issue(
                requirement_id,
                "Expected at least one file-list row with "
                f"'{expected_name}' equal to one of: "
                f"{', '.join(required_row['acceptedValues'])}.",
            )
        ]

    @staticmethod
    def _issue(
        requirement_id: str,
        message: str,
        severity: Severity = Severity.ERROR,
    ) -> ValidationError:
        return ValidationError(
            severity=severity,
            location_description="BIA submission profile",
            message=f"[{requirement_id}] {message}",
        )
