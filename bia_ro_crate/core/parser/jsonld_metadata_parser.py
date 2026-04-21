import json
from pathlib import Path

import pydantic
import pyld
from bia_ro_crate.models.linked_data.ld_context import (
    ContextTerm,
    SimpleJSONLDContext,
)
from bia_ro_crate.models.linked_data.ontology_terms import DUBLINCORE
from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel
from bia_ro_crate.models.ro_crate_generator_utils import (
    generate_standard_bia_context,
    get_all_ro_crate_classes,
)
from pydantic_core import ErrorDetails
from rdflib import RDF, Graph, URIRef
from bia_ro_crate.core.bia_ro_crate_metadata import BIAROCrateMetadata
from bia_ro_crate.core.parser.ro_crate_metadata_parser import (
    ROCrateMetadataParser,
)
from bia_ro_crate.core.validation.severity import Severity
from bia_ro_crate.core.validation.validation_error import ValidationError
from rocrate_validator import models, services


class JSONLDMetadataParser(ROCrateMetadataParser):
    """
    Parser for the ro-crate-metadata.json file in an ro-crate, producing a BIAROCrateMetadata.
    """

    parser_classes_map: dict[URIRef, type[ROCrateModel]]
    DEFAULT_RO_CRATE_FILENAME: str = "ro-crate-metadata.json"

    def __init__(self, ro_crate_root: Path | str, context: dict | None = None) -> None:
        if context and "parser_classes" in context:
            parser_classes_map: dict[URIRef, type[ROCrateModel]] = {
                ro_crate_class.model_config["model_type"]: ro_crate_class
                for ro_crate_class in context["parser_classes"]
            }
        else:
            parser_classes_map = get_all_ro_crate_classes()
        self.parser_classes_map = parser_classes_map

        super().__init__(ro_crate_root=ro_crate_root, context=context)

    def parse(self, target: Path | str | None = None) -> None:
        if target is None:
            target = self.DEFAULT_RO_CRATE_FILENAME
        crate_metadata_path = self._get_metadata_path(target)
        self._pre_parse_validation(crate_metadata_path)

        with open(crate_metadata_path, "r") as jsonfile:
            json_dict = json.load(jsonfile)

        context = self._parse_context(json_dict["@context"])
        rocrate_objects_by_id = self._parse_objects(json_dict["@graph"], context)

        self._result = BIAROCrateMetadata(
            graph_bia_entities=rocrate_objects_by_id,
            context=context,
            base_path=crate_metadata_path.parent,
        )

    @staticmethod
    def _format_pydantic_error(error_dict: ErrorDetails) -> str:
        loc = error_dict["loc"]
        msg = error_dict["msg"]

        if error_dict["type"] == "missing":
            return f"Missing required field: {loc[0]}"

        match len(loc):
            case 0:
                return msg
            case 1:
                return f"At {loc[0]}: {msg}"
            case _:
                return f"At {loc[0]}, index: {loc[1]}: {msg}"

    def _parse_objects(self, entities, context):

        rocrate_objects_by_id = {}
        for entity in entities:
            expanded_entity = self._expand_entity(entity, context.to_dict())
            entity_types = set(URIRef(str(x)) for x in expanded_entity.get("@type", ()))

            matched_model_types = self._get_class_intersection(entity_types)

            if (matched_model_count := len(matched_model_types)) != 1:
                self._parse_issues.append(
                    ValidationError(
                        severity=Severity.ERROR,
                        location_description=f"At ro-crate object with @id: {expanded_entity.get('@id')}",
                        message=f"@type of object does not contain exactly 1 BIA classes. @type contains: {', '.join(entity_types)}, matching {matched_model_count} BIA classes.",
                    )
                )
                continue

            entity_type = matched_model_types.pop()
            ro_crate_model = self.parser_classes_map[entity_type]

            try:
                object = ro_crate_model(**entity)
            except pydantic.ValidationError as error:
                self._parse_issues.append(
                    ValidationError(
                        severity=Severity.ERROR,
                        location_description=f"At ro-crate object with @id: {expanded_entity.get('@id', 'Unknown ID')}",
                        message="\n".join(
                            self._format_pydantic_error(e) for e in error.errors()
                        ),
                    )
                )
                continue

            if object.id in rocrate_objects_by_id:
                self._parse_issues.append(
                    ValidationError(
                        severity=Severity.ERROR,
                        location_description=f"At ro-crate object with @id: {object.id}",
                        message=f"Found more than one object with @id {object.id}.",
                    )
                )
            rocrate_objects_by_id[object.id] = object

        self._raise_errors()
        return rocrate_objects_by_id

    def _get_metadata_path(self, target: Path | str | None) -> Path:
        if target:
            return self._ro_crate_root / target
        else:
            return self._ro_crate_root / self.DEFAULT_RO_CRATE_FILENAME

    def _get_class_intersection(self, object_types: set[URIRef]) -> set[URIRef]:
        return set(self.parser_classes_map.keys()) & object_types

    @staticmethod
    def _expand_entity(
        entity: dict, context: dict | list | str
    ) -> dict[str, str | list[dict] | list[str]]:
        document = {"@context": context, "@graph": [entity]}
        expanded = pyld.jsonld.expand(document)
        return expanded[0]

    def _parse_context(
        self,
        context: dict | list | str,
    ) -> SimpleJSONLDContext.SimpleJSONLDContext:
        """
        Parses this @context object
        """
        # Using pyld's JsonLdProcessor to handle the possible variablitiy in context definition structure
        jsonld_processor = pyld.jsonld.JsonLdProcessor()
        mappings = jsonld_processor.process_context(
            active_ctx={"mappings": {}}, local_ctx=context, options=None
        )["mappings"]

        standard_bia_context = generate_standard_bia_context()

        terms = set()
        prefixes = {}
        for term_key, mapping in mappings.items():
            if mapping.get("_prefix"):
                prefixes[term_key] = mapping.get("@id")
            else:
                term = ContextTerm.ContextTerm(
                    full_uri=mapping.get("@id"),
                    field_name=term_key,
                    is_reverse=mapping.get("reverse"),
                )
                if (
                    term_key in standard_bia_context.terms
                    and standard_bia_context.terms[term_key] != term
                ):
                    self._parse_issues.append(
                        ValidationError(
                            message=f"Term has been remapped in context: {term_key} must be mapped to {standard_bia_context.terms[term_key].full_uri}",
                            location_description=f"At {term_key}",
                            severity=Severity.ERROR,
                        )
                    )
                else:
                    terms.add(term)

        self._raise_errors()
        return SimpleJSONLDContext.SimpleJSONLDContext(prefixes=prefixes, terms=terms)

    def _pre_parse_validation(self, ro_crate_metadata_path: Path) -> None:
        self._id_reference_validation(ro_crate_metadata_path)
        self._base_ro_crate_validation(ro_crate_metadata_path)
        self._raise_errors()

    def _id_reference_validation(self, ro_crate_metadata_path: Path) -> None:
        """
        Validates that, for all statements, <subject> <predicate> <object>:
        1. All <objects> that are URIReferences exist in the document (for relevant properties)
        2. No <subject> exists that doesn't have connections back to the ro-crate-metadata.json .

        Currently for 1 is taking all URIRef <objects>, then removing those where the <predicate> was RDF.type, or DUBLINCORE.conformsTo, since these are expected to be external references.
        The propertyURL for columns is expected to apepar as a string rather than a URIRef.
        """

        graph = Graph()
        graph.parse(ro_crate_metadata_path, format="json-ld")

        subjects = set(s for s in graph.subjects(unique=True) if isinstance(s, URIRef))

        type_objects = set(
            type_reference
            for type_reference in graph.objects(predicate=RDF.type, unique=True)
            if isinstance(type_reference, URIRef)
        )
        profiles = set(
            ro_crate_profile
            for ro_crate_profile in graph.objects(
                predicate=DUBLINCORE.conformsTo, unique=True
            )
            if isinstance(ro_crate_profile, URIRef)
        )
        uri_referenced_object = set(
            o for o in graph.objects(unique=True) if isinstance(o, URIRef)
        )
        uri_referenced_object -= type_objects
        uri_referenced_object -= profiles
        undefined_references = uri_referenced_object - subjects
        inboundless_subjects = subjects - uri_referenced_object

        metadata_uri = URIRef(ro_crate_metadata_path.resolve().as_uri())
        if metadata_uri in inboundless_subjects:
            inboundless_subjects.remove(metadata_uri)

        if len(inboundless_subjects) > 0:
            self._parse_issues.append(
                ValidationError(
                    message=(
                        "Found objects in ro-crate-metadata.json with no inbound "
                        f"references: {', '.join(sorted(str(subject) for subject in inboundless_subjects))}"
                    ),
                    severity=Severity.INFO,
                )
            )

        if len(undefined_references) > 0:
            self._parse_issues.append(
                ValidationError(
                    message=f"Found undefined references: {', '.join(undefined_references)}",
                    severity=Severity.ERROR,
                )
            )

    def _base_ro_crate_validation(self, ro_crate_metadata_path: Path) -> None:
        """
        Checks for any errors being raised from the generic ro-crate validator.
        This will check that the ro-crate:
            - has a @context,
            - has a @graph,
            - is flattend json-ld
            - every field has a term in the context
            - the minimum properties are defined on the ro-crate-metadata object, root dataset object, and that File & Dataset objects are connected back to the root dataset.

        SHACL shapes can be used as a profile definition to validate the graph, but we currently do not use this.
        """
        settings = services.ValidationSettings(
            rocrate_uri=ro_crate_metadata_path.parent,
            profile_identifier="ro-crate-1.1",
            requirement_severity=models.Severity.REQUIRED,
        )

        result = services.validate(settings)

        severity_map = {
            "REQUIRED": "ERROR",
            "RECOMMENDED": "WARNING",
            "OPTIONAL": "INFO",
        }

        if result.has_issues():
            for issue in result.issues:
                error_location = (
                    f"At ro-crate object with @id: {issue.violatingEntity}"
                    if issue.violatingEntity
                    else None
                )
                self._parse_issues.append(
                    ValidationError(
                        severity=Severity(
                            severity_map.get(issue.severity.name, "INFO")
                        ),
                        location_description=error_location,
                        message=(
                            issue.message
                            if issue.message
                            else "ro-crate shacl validation failed without message."
                        ),
                    )
                )
