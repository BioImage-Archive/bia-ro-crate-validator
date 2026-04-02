from pathlib import Path
from urllib.parse import quote, unquote

import pandas as pd
from bia_ro_crate.models import ro_crate_models
from bia_ro_crate.models.linked_data.ontology_terms import BIA, SCHEMA
from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel
from rdflib import RDF, URIRef
from bia_ro_crate.core.bia_ro_crate_metadata import BIAROCrateMetadata
from bia_ro_crate.core.file_list import FileList
from bia_ro_crate.core.parser.metadata_parser import MetadataParser

from ..validation import Severity, ValidationError


class FileListParser(MetadataParser[FileList]):
    _ro_crate_metadata: BIAROCrateMetadata
    _file_list_id: str
    _file_list_path: Path
    _file_path_column_id: str
    ROC_METADATA_LOOKUP_TYPES = {
        BIA.associatedBiologicalEntity: ro_crate_models.BioSample,
        BIA.associatedImagingPreparationProtocol: ro_crate_models.SpecimenImagingPreparationProtocol,
        BIA.associatedImageAcquisitionProtocol: ro_crate_models.ImageAcquisitionProtocol,
        BIA.associatedAnnotationMethod: ro_crate_models.AnnotationMethod,
        BIA.associatedProtocol: ro_crate_models.Protocol,
        BIA.associatedSubject: ro_crate_models.Specimen,
        SCHEMA.isPartOf: ro_crate_models.Dataset,
    }
    DATA_SELF_LOOKUP_TYPES = {BIA.associatedSourceImage: BIA.Image}

    def __init__(
        self,
        ro_crate_metadata: BIAROCrateMetadata,
        *,
        context: dict | None = None,
    ) -> None:

        self._ro_crate_metadata = ro_crate_metadata
        super().__init__(
            ro_crate_root=self._ro_crate_metadata.get_base_path(), context=context
        )

    def _set_file_list_path_and_id(self, target: Path | str | None):
        if not target:
            target = str(self._ro_crate_metadata.get_file_list_entity().id)

        if str(target) in self._ro_crate_metadata.get_object_lookup():
            file_list_id = str(target)
            file_list_path = self._ro_crate_root / unquote(str(target))
            if not file_list_path.exists or not file_list_path.is_file:
                raise ValueError(f"File list {file_list_path} not found")
        else:
            file_list_id = quote(str(target))
            file_list_path = self._ro_crate_root / target
            if file_list_id not in self._ro_crate_metadata.get_object_lookup():
                raise ValueError("File list not described in ro-crate-metadata")

        self._file_list_path = file_list_path
        self._file_list_id = file_list_id
        self._raise_errors()

    def _get_schema(self) -> dict[str, ro_crate_models.Column]:

        file_list: ro_crate_models.FileList = (
            self._ro_crate_metadata.get_file_list_entity()
        )

        schema_object: ro_crate_models.TableSchema = self._ro_crate_metadata.get_object(
            file_list.tableSchema.id
        )

        columns: dict[str, ro_crate_models.Column] = {
            column_ref.id: self._ro_crate_metadata.get_object(column_ref.id)
            for column_ref in schema_object.column
        }

        required_properties = {BIA.filePath, SCHEMA.isPartOf}
        column_by_property = {}

        for column_id, column in columns.items():
            if column.propertyUrl:
                column_by_property[URIRef(column.propertyUrl)] = column_id

        for required_property in required_properties:
            if required_property not in column_by_property:
                self._parse_issues.append(
                    ValidationError(
                        severity=Severity.ERROR,
                        location_description=f"At file list {file_list.id} and TableSchema {schema_object.id}",
                        message=f"Missing column with required property: {required_property}",
                    )
                )

        self._raise_errors()
        self._file_path_column_id = column_by_property[BIA.filePath]
        return columns

    def _validate_reference_columns(
        self, data: pd.DataFrame, columns: dict[str, ro_crate_models.Column]
    ):
        self._validate_ro_crate_reference_columns(data, columns)
        self._validate_self_reference_columns(data, columns)
        self._raise_errors()

    def _validate_self_reference_columns(
        self, data: pd.DataFrame, columns: dict[str, ro_crate_models.Column]
    ):
        """
        Check that when the values in a column that is expected to correspond to a name or file path in another column in the file list,
        a row exists with that value, and there is a type column with the expected type for the row.

        For example: if there is a column named 'inputImage' with propertyUrl 'bia:associatedSourceImage', and a row with value 'path/to/input/image.tiff',
        there should be a row that includes 'path/to/input/image.tiff' and 'bia:Image' for the bia:filePath/schema:name and rdf:type columns respectively.
        """
        columns_to_check: dict[str, URIRef] = {}
        target_columns = {}
        type_column = None

        for column in columns.values():
            if column.propertyUrl:
                property_uri = URIRef(column.propertyUrl)
                if property_uri in self.DATA_SELF_LOOKUP_TYPES:
                    columns_to_check[column.columnName] = self.DATA_SELF_LOOKUP_TYPES[
                        property_uri
                    ]

                if property_uri in (BIA.filePath, SCHEMA.name):
                    target_columns[property_uri] = column.columnName

                if property_uri == RDF.type:
                    type_column = column.columnName

        if len(columns_to_check) == 0:
            return

        if not type_column:
            self._parse_issues.append(
                ValidationError(
                    severity=Severity.ERROR,
                    message=f"File list contains columns that reference others ({', '.join(columns_to_check.keys())}) but no column with propertyUrl rdf:type.",
                )
            )
            return

        name_type_map: dict[str, str] = {}
        file_type_map: dict[str, str] = dict(
            zip(data[target_columns[BIA.filePath]], data[type_column])
        )
        if target_columns.get(SCHEMA.name):
            name_type_map = dict(
                zip(data[target_columns[SCHEMA.name]], data[type_column])
            )

        errors = []
        for index, row in data.iterrows():
            self._check_row_reference_against_filelist(
                row,
                file_type_map,
                name_type_map,
                columns_to_check,
                columns[self._file_path_column_id].columnName,
                errors,
            )

        self._parse_issues += errors

    def _validate_ro_crate_reference_columns(
        self, data: pd.DataFrame, columns: dict[str, ro_crate_models.Column]
    ):
        """
        Check that when the values in a column that is expected to correspond to an ID of an object in the ro-crate-metadata.json,
        that object exists in the ro-crate-metadata.json, and is of the expected type.

        For example: if there is a column named 'dataset' with propertyUrl 'schema:isPartOf', and a row with value '#dataset_1',
        there should be a bia:Dataset object in the ro-crate-metadata.json with @id of '#dataset_1'.
        """
        columns_to_check = {
            column.columnName: self.ROC_METADATA_LOOKUP_TYPES[
                URIRef(column.propertyUrl)
            ]
            for column in columns.values()
            if column.propertyUrl
            and URIRef(column.propertyUrl) in self.ROC_METADATA_LOOKUP_TYPES
        }

        errors = data.apply(
            self._check_row_reference_and_type_against_roc_metadata,
            args=(
                self._ro_crate_metadata.get_object_lookup(),
                columns_to_check,
                columns[self._file_path_column_id].columnName,
            ),
            axis=1,
        )

        self._parse_issues += errors.dropna().to_list()

    @staticmethod
    def _check_row_reference_and_type_against_roc_metadata(
        row,
        roc_metadata_lookup: dict[str, ROCrateModel],
        columns_to_check: dict[str, type[ROCrateModel]],
        file_path_column_name: str,
    ):
        for column in columns_to_check:
            references = row[column]

            if not isinstance(references, list) and pd.isna(references):
                continue

            if isinstance(references, str):
                references = [references]

            for reference in references:
                message = None
                if reference not in roc_metadata_lookup:
                    message = f"{reference} does not exist in ro-crate-metadata.json"
                elif not isinstance(
                    roc_metadata_lookup[reference], columns_to_check[column]
                ):
                    message = f"{reference} references an object of unexpected type."

                if message:
                    return ValidationError(
                        severity=Severity.ERROR,
                        message=message,
                        location_description=f"In file list, at row: {row[file_path_column_name]}.",
                    )

    @staticmethod
    def _check_row_reference_against_filelist(
        row,
        file_type_lookup: dict[str, str],
        name_type_lookup: dict[str, str],
        columns_to_check: dict[str, URIRef],
        file_path_column_name: str,
        error_aggregator: list,
    ):
        for column_name, expected_type in columns_to_check.items():
            references = row[column_name]

            if not isinstance(references, list) and pd.isna(references):
                continue

            if isinstance(references, str):
                references = [references]

            for reference in references:
                actual_type = None
                # Check against file paths
                if reference in name_type_lookup:
                    actual_type = name_type_lookup[reference]
                elif reference in file_type_lookup:
                    actual_type = file_type_lookup[reference]
                else:
                    error_aggregator.append(
                        ValidationError(
                            severity=Severity.ERROR,
                            message=f"Reference '{reference}' not found in file list.",
                            location_description=f"In file list, at row: {row[file_path_column_name]}",
                        )
                    )
                    continue

                # Check if the type matches the expected type
                if (
                    pd.isna(actual_type)
                    or not actual_type
                    or URIRef(actual_type) != expected_type
                ):
                    message = (
                        f"Reference '{reference}' has no rdf:type, expected '{expected_type}'."
                        if (pd.isna(actual_type) or not actual_type)
                        else f"Reference '{reference}' has rdf:type '{actual_type}', expected '{expected_type}'."
                    )
                    error_aggregator.append(
                        ValidationError(
                            severity=Severity.ERROR,
                            message=message,
                            location_description=f"In file list, at row: {row[file_path_column_name]}",
                        )
                    )
