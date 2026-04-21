from bia_ro_crate.core.bia_ro_crate_metadata import BIAROCrateMetadata
from bia_ro_crate.core.file_list import FileList


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
