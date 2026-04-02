import logging
from pathlib import Path

from bia_ro_crate.core.parser import JSONLDMetadataParser, TSVMetadataParser

logger = logging.getLogger("__main__." + __name__)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("rdflib").setLevel(logging.ERROR)


def bia_roc_validation(ro_crate_directory: Path):

    roc_metadata = None
    try:
        roc_metadata_parser = JSONLDMetadataParser(ro_crate_directory)
        roc_metadata_parser.parse()
        roc_metadata = roc_metadata_parser.result
    except ExceptionGroup as validationExceptionGroup:
        for exception in validationExceptionGroup.exceptions:
            logger.error(exception)
        exit(1)


    try:
        file_list_parser = TSVMetadataParser(roc_metadata)
        file_list_parser.parse()
        file_list_parser.result
    except ExceptionGroup as validationExceptionGroup:
        for exception in validationExceptionGroup.exceptions:
            logger.error(exception)
        exit(1)
