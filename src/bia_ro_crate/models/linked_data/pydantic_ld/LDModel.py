from collections import Counter
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field
from rdflib.graph import Graph

from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm
from bia_ro_crate.models.linked_data.pydantic_ld.FieldContext import FieldContext
from bia_ro_crate.models.linked_data.pydantic_ld.model_consistency import (
    OntologyConsistencyReport,
    inspect_model,
)
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
            if field_info.exclude is True:
                continue
            contexts = [m for m in field_info.metadata if isinstance(m, FieldContext)]
            if len(contexts) > 1:
                raise ValueError(f"{cls.__name__}.{field_name}: multiple FieldContexts")
            field_context = contexts[0] if contexts else None

            if field_context:
                name = field_name
                if by_alias and field_info.serialization_alias is not None:
                    name = field_info.serialization_alias
                if not name or name.startswith("@") or serialised_names[name] > 1:
                    raise ValueError(f"{cls.__name__}: conflicting context term {name}")
                term = field_context.to_context_term(name, compacted_ids=compacted_ids)

                field_contexts.append(term)

        return field_contexts

    @classmethod
    def validate_ontology_field_consistency(cls, ontology: Graph) -> None:
        """Check declared field shapes and named-class implications recursively.

        Raise OntologyValidationError containing all discovered issues. This is
        a static declaration check, not instance validation or an OWL reasoner.
        Unsupported annotations/anonymous class or datatype expressions are
        reported explicitly rather than assumed compatible.
        """
        cls.ontology_consistency_report(ontology).raise_for_errors()

    @classmethod
    def ontology_consistency_report(cls, ontology: Graph) -> OntologyConsistencyReport:
        """Inspect declarations without rebuilding models or resolving references.

        ``ok`` means no errors in the supported static fragment. Notices describe
        missing vocabulary coverage, unresolved targets and unchecked values.
        Reused model/type contexts have one representative diagnostic path.
        """
        return inspect_model(cls, ontology, ObjectReference)

    @classmethod
    def is_valid(cls, ontology: Graph) -> bool:
        return cls.ontology_consistency_report(ontology).ok
