from copy import deepcopy
from typing import Iterable

from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm


class SimpleJSONLDContext:
    prefixes: dict[str, str]
    terms: dict[str, ContextTerm]

    def __init__(
        self,
        prefixes: dict[str, str] | None = None,
        terms: Iterable[ContextTerm] | None = None,
        force_type_container: bool = False,
        rename_type_key: str | None = None,
        renamed_id_key: str | None = None,
    ):
        self.prefixes = {}
        self.terms = {}
        self._special_mappings: dict[str, object] = {}
        for name, iri in (prefixes or {}).items():
            self.add_prefix(name, iri)
        for term in terms or ():
            self.add_term(term)

        if force_type_container or rename_type_key:
            self.add_type_container(
                key=rename_type_key or "@type",
                force_type_container=force_type_container,
            )

        if renamed_id_key:
            self.add_id_rename(renamed_id_key)

    def to_dict(self) -> dict:
        # Conventional namespaces imply a prefix; other IRIs need an explicit flag.
        context_dict = {
            prefix: iri if iri.endswith(("/", "#")) else {"@id": iri, "@prefix": True}
            for prefix, iri in self.prefixes.items()
        }

        for term in self.terms.values():
            context_dict |= term.to_mapping_dict(self.prefixes)

        # merge any special mappings (e.g. @type container entries or renamed @id)
        if getattr(self, "_special_mappings", None):
            context_dict |= deepcopy(self._special_mappings)

        return dict(sorted(context_dict.items()))

    def add_type_container(
        self, key: str = "@type", force_type_container: bool = False
    ) -> None:
        type_expanded_term = {}

        if force_type_container:
            type_expanded_term["@container"] = "@set"

        if key != "@type":
            type_expanded_term["@id"] = "@type"

        if type_expanded_term:
            self._check_definition(key, "_special_mappings", type_expanded_term)
            self._special_mappings[key] = type_expanded_term

    def add_id_rename(self, key: str) -> None:
        if key == "@id":
            return
        mapping = {"@id": "@id"}
        self._check_definition(key, "_special_mappings", mapping)
        self._special_mappings[key] = mapping

    def _check_definition(self, name, owner, value):
        # Only @type can be defined as a keyword, to set its container.
        if name.startswith("@") and (
            owner != "_special_mappings" or name != "@type" or "@id" in value
        ):
            raise ValueError(f"Reserved context term: {name}")
        for collection in ("prefixes", "terms", "_special_mappings"):
            entries = getattr(self, collection)
            if name in entries and (collection != owner or entries[name] != value):
                raise ValueError(f"Context definition conflict: {name}")

    def add_prefix(self, short_term: str, uri: str) -> None:
        if not isinstance(short_term, str) or not isinstance(uri, str):
            raise TypeError("Prefix names and IRIs must be strings")
        short_term, uri = str(short_term), str(uri)
        self._check_definition(short_term, "prefixes", uri)
        self.prefixes[short_term] = uri

    def remove_prefix(self, prefix) -> None:
        self.prefixes.pop(prefix)

    def add_term(self, term: ContextTerm) -> None:
        self._check_definition(term.field_name, "terms", term)
        self.terms[term.field_name] = term

    def remove_term(self, term: ContextTerm | str) -> None:
        if isinstance(term, ContextTerm):
            if term.field_name in self.terms and self.terms[term.field_name] == term:
                self.terms.pop(term.field_name)
        elif isinstance(term, str):
            self.terms.pop(term)
        else:
            raise TypeError(
                f"term {term} is not a string field name, nor a ContextTerm"
            )

    def merge(self, *contexts: "SimpleJSONLDContext") -> "SimpleJSONLDContext":
        """Merge detached definitions, rejecting names with conflicting meanings."""
        merged = SimpleJSONLDContext()
        for context in (self, *contexts):
            for owner in ("prefixes", "terms", "_special_mappings"):
                for name, value in getattr(context, owner).items():
                    merged._check_definition(name, owner, value)
                    getattr(merged, owner)[name] = deepcopy(value)
        return merged
