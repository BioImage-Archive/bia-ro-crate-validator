from pathlib import Path

import pandas as pd
from collections.abc import Iterable
from rdflib import URIRef

from bia_ro_crate.core.bia_ro_crate_metadata import BIAROCrateMetadata
from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.core.file_list import FileList
from bia_ro_crate.core.parser.file_list_parser import FileListParser
from bia_ro_crate.core.parser.base_parser import Parser
from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser
from bia_ro_crate.core.parser.tsv_metadata_parser import TSVMetadataParser
from bia_ro_crate.core.validation.severity import Severity
from bia_ro_crate.core.validation.validation_error import ValidationError


class ROCrateParser(Parser[BIASubmissionMetadata]):
    def parse(self, target: Path | str | None = None) -> None:
        metadata_parser = JSONLDMetadataParser(self._ro_crate_root)
        try:
            metadata_parser.parse(target=target)
        finally:
            self._parse_issues.extend(metadata_parser.issues)

        metadata = metadata_parser.result

        # TODO: Select a file list parser based on the declared file list format.
        file_list_parser = TSVMetadataParser(metadata)
        try:
            file_list_parser.parse()
        finally:
            self._parse_issues.extend(file_list_parser.issues)

        file_list = file_list_parser.result

        self._validate_crate_connectivity(metadata, file_list)
        self._raise_errors()

        self._result = BIASubmissionMetadata(metadata=metadata, file_list=file_list)

    def _validate_crate_connectivity(
        self,
        metadata: BIAROCrateMetadata,
        file_list: FileList,
    ) -> None:
        metadata_ids = set(metadata.get_object_lookup())
        referenced_ids = self._metadata_reference_ids(metadata)
        referenced_ids.update(self._file_list_reference_ids(file_list))

        unconnected_ids = sorted(
            metadata_ids
            - referenced_ids
            - {metadata.DEFAULT_RO_CRATE_FILENAME}
        )

        if unconnected_ids:
            self._parse_issues.append(
                ValidationError(
                    severity=Severity.WARNING,
                    message=(
                        "Found RO-Crate objects with no inbound references across "
                        "ro-crate-metadata.json and file list references: "
                        f"{', '.join(unconnected_ids)}"
                    ),
                )
            )

    def _metadata_reference_ids(self, metadata: BIAROCrateMetadata) -> set[str]:
        references: set[str] = set()
        for entity in metadata.get_objects():
            entity_dict = entity.model_dump(by_alias=True, mode="json")
            for key, value in entity_dict.items():
                if key in {"@id", "@type"}:
                    continue
                references.update(self._collect_object_reference_ids(value))
        return references

    def _file_list_reference_ids(self, file_list: FileList) -> set[str]:
        reference_column_ids = {
            column_id
            for column_id, property_url in file_list.get_column_properties().items()
            if property_url
            and URIRef(str(property_url)) in FileListParser.ROC_METADATA_LOOKUP_TYPES
        }

        references: set[str] = set()
        for column_id in reference_column_ids:
            for value in file_list.data[column_id]:
                references.update(self._normalise_file_list_value(value))
        return references

    @classmethod
    def _collect_object_reference_ids(cls, value: object) -> set[str]:
        if isinstance(value, dict):
            if set(value.keys()) == {"@id"} and isinstance(value["@id"], str):
                return {value["@id"]}

            nested_references: set[str] = set()
            for nested_value in value.values():
                nested_references.update(cls._collect_object_reference_ids(nested_value))
            return nested_references

        if isinstance(value, list):
            nested_references: set[str] = set()
            for nested_value in value:
                nested_references.update(cls._collect_object_reference_ids(nested_value))
            return nested_references

        return set()

    @staticmethod
    def _normalise_file_list_value(value: object) -> Iterable[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item)]

        if isinstance(value, str):
            return [value] if value else []

        if pd.isna(value):
            return []

        return [str(value)]
