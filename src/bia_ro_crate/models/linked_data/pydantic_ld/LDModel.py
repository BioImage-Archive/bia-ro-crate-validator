from collections import Counter
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field
from rdflib import OWL, RDF
from rdflib.graph import Graph

from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm
from bia_ro_crate.models.linked_data.pydantic_ld.FieldContext import FieldContext
from bia_ro_crate.models.linked_data.pydantic_ld.utils import id_validate


class ObjectReference(BaseModel):
    id: Annotated[str, AfterValidator(id_validate)] = Field(alias="@id")


class LDModel(BaseModel):
    @classmethod
    def generate_field_context(
        cls, compacted_ids: bool = False, *, by_alias: bool = False
    ) -> list[ContextTerm]:
        """Generate property terms for Python names or serialisation aliases.

        Enable ``compacted_ids`` for string-valued references that need JSON-LD
        ``@id`` coercion. Leave it disabled for explicit ``{"@id": ...}`` objects.
        Containers and reverse properties come from each field's FieldContext;
        document-level settings belong to SimpleJSONLDContext.
        """
        field_contexts = []
        names = set()
        serialised_names = Counter(
            (
                info.serialization_alias
                if by_alias and info.serialization_alias is not None
                else name
            )
            for name, info in cls.model_fields.items()
            if info.exclude is not True
        )

        for field_name, field_info in cls.model_fields.items():
            contexts = [m for m in field_info.metadata if isinstance(m, FieldContext)]
            if len(contexts) > 1:
                raise ValueError(f"{cls.__name__}.{field_name}: multiple FieldContexts")
            field_context = contexts[0] if contexts else None

            if field_context:
                name = field_name
                if by_alias and field_info.serialization_alias is not None:
                    name = field_info.serialization_alias
                if (
                    not name
                    or name.startswith("@")
                    or name in names
                    or serialised_names[name] > 1
                ):
                    raise ValueError(f"{cls.__name__}: conflicting context term {name}")
                names.add(name)
                term = field_context.to_context_term(name, compacted_ids=compacted_ids)

                field_contexts.append(term)

        return field_contexts

    @classmethod
    def validate_ontology_field_consistency(cls, ontology: Graph):
        # TODO: make this collect error and list all issues
        for field_name, field_info in cls.model_fields.items():
            field_context = next(
                (m for m in field_info.metadata if isinstance(m, FieldContext)), None
            )

            if field_context:
                # Check uri exists in ontology
                if field_context.uri not in ontology.subjects():
                    raise KeyError(
                        f"Field {field_name} has a context uri {field_context.uri} that is not in the ontology"
                    )

                # Check uri for field is a property
                if not any(
                    object_type
                    in [
                        OWL.ObjectProperty,
                        OWL.DatatypeProperty,
                        OWL.AnnotationProperty,
                        RDF.Property,
                    ]
                    for object_type in ontology.objects(field_context.uri, RDF.type)
                ):
                    raise ValueError(
                        f"Field {field_name} has a context uri {field_context.uri} that is not a property in the ontology"
                    )

            # TODO: add check that pydantic type is a reasonable match for the ontology type
            # TODO: add check that none of the inferred types of the model are owl:disjoint with each other
            # TODO: check for validation recursively in nested models, including that the inferred types from the parent model are compatible with the child model

    @classmethod
    def is_valid(cls, ontology: Graph):
        try:
            cls.validate_ontology_field_consistency(ontology)
        except Exception:
            return False

        return True
