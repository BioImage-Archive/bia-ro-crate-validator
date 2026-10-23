from typing import TYPE_CHECKING

from bia_ro_crate.core.bia_ro_crate_metadata import BIAROCrateMetadata
from bia_ro_crate.core.file_list import FileList

if TYPE_CHECKING:
    from bia_ro_crate.core.editing import SubmissionEditor


class BIASubmissionMetadata:
    metadata: BIAROCrateMetadata
    file_list: FileList

    def __init__(
        self,
        metadata: BIAROCrateMetadata,
        file_list: FileList,
    ) -> None:
        self.metadata = metadata
        self.file_list = file_list

    def editor(self) -> "SubmissionEditor":
        """Create an isolated editor; this submission remains unchanged."""
        # Import here because SubmissionEditor also imports BIASubmissionMetadata.
        from bia_ro_crate.core.editing import SubmissionEditor

        return SubmissionEditor(self)
