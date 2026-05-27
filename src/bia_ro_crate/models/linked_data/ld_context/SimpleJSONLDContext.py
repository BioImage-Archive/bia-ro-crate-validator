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
        self.prefixes = prefixes if prefixes else {}
        self.terms = {term.field_name: term for term in terms} if terms else {}
        self._special_mappings: dict[str, object] = {}

        if force_type_container or rename_type_key:
            self.add_type_container(key=rename_type_key or "@type", force_type_container=force_type_container)

        if renamed_id_key:
            self.add_id_rename(renamed_id_key)

    def to_dict(self) -> dict:
        context_dict = self.prefixes.copy()

        for term in self.terms.values():
            context_dict |= term.to_mapping_dict(self.prefixes)

        # merge any special mappings (e.g. @type container entries or renamed @id)
        if getattr(self, "_special_mappings", None):
            context_dict |= self._special_mappings

        return dict(sorted(context_dict.items()))

    def add_type_container(self, key: str = "@type", force_type_container: bool = False) -> None:
        type_expanded_term = {}

        if force_type_container:
            type_expanded_term["@container"] = "@set"

        if key != "@type":
            type_expanded_term["@id"] = "@type"

        if type_expanded_term:
            self._special_mappings[key] = type_expanded_term

    def add_id_rename(self, key: str) -> None:
        if key == "@id":
            return
        self._special_mappings[key] = {"@id": "@id"}

    def add_prefix(self, short_term: str, uri: str) -> None:
        self.prefixes[short_term] = uri

    def remove_prefix(self, prefix) -> None:
        self.prefixes.pop(prefix)

    def add_term(self, term: ContextTerm) -> None:
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

    def merge(
        self, *contexts: Iterable["SimpleJSONLDContext"]
    ) -> "SimpleJSONLDContext":
        """Merge multiple SimpleJSONLDContext instances into a new one."""
        merged_prefixes = self.prefixes.copy()
        merged_terms = self.terms.copy()

        context: SimpleJSONLDContext
        for context in contexts:
            for prefix, uri in context.prefixes.items():
                if prefix in merged_prefixes and merged_prefixes[prefix] != uri:
                    raise ValueError(f"Prefix conflict: {prefix} maps to multiple URIs")
                merged_prefixes[prefix] = uri

            existing_fields = {term.field_name for term in merged_terms.values()}
            for term_field_name, term in context.terms.items():
                if term_field_name not in existing_fields:
                    merged_terms[term_field_name] = term

        return SimpleJSONLDContext(
            prefixes=merged_prefixes, terms=merged_terms.values()
        )
