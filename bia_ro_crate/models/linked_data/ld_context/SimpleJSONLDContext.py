from typing import Iterable

from .ContextTerm import ContextTerm


class SimpleJSONLDContext:
    prefixes: dict[str, str]
    terms: dict[str, ContextTerm]

    def __init__(
        self,
        prefixes: dict[str, str] | None = None,
        terms: Iterable[ContextTerm] | None = None,
    ):
        self.prefixes = prefixes if prefixes else {}
        self.terms = {term.field_name: term for term in terms} if terms else {}

    def to_dict(self) -> dict:
        context_dict = self.prefixes.copy()

        for term in self.terms.values():
            context_dict |= term.to_mapping_dict(self.prefixes)

        return dict(sorted(context_dict.items()))

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
