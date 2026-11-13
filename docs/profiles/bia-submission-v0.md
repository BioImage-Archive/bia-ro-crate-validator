# BIA submission profile v0

**Profile identifier:** `bia-submission-v0`

This profile describes the RO-Crate metadata and file list for a BioImage Archive (BIA) submission. It extends the validator's `minimal` profile with submission-specific checks. The minimal profile remains the default when no profile is selected.

This document describes the current implementation and the agreed v0 choices. The [BIA data models](../../src/bia_ro_crate/models/ro_crate_models.py) define the representations of individual properties, and the [profile implementation](../../src/bia_ro_crate/validator/profiles/bia_submission_v0.py) defines the additional checks.

## Validate a submission

```shell
bia-ro-crate validate /path/to/submission --profile bia-submission-v0
bia-ro-crate validate /path/to/submission --profile bia-submission-v0 --report-json
```

In Python:

```python
from pathlib import Path
from bia_ro_crate.validator import bia_roc_validation

report = bia_roc_validation(
    Path("/path/to/submission"),
    validation_mode="report",
    profile="bia-submission-v0",
)
```

Required violations are reported as errors. Missing recommended properties are reported as warnings. The existing validation summary and report structure are used for both profiles. Profile-specific checks run after successful parsing; when parsing fails, the parser's findings are reported first. In the existing JSON report mode, inspect `highest_error_level` and `issues` for the outcome; the CLI retains its existing report-mode exit behaviour.

## Submission structure

A submission contains `ro-crate-metadata.json` and a TSV file named `file_list.tsv`. The metadata must describe exactly one BIA study and one BIA file list, and at least one BIA dataset. The study is the root dataset of the RO-Crate, and its `hasPart` references every BIA dataset and the file list.

The file list entity has `@id` `file_list.tsv` and includes the types `File`, `bia:FileList`, and `csvw:Table`. It refers to a `csvw:Schema` whose `csvw:Column` entities define the file-list columns.

The inherited minimal checks apply, including the RO-Crate 1.1 checks, JSON-LD context and reference validation, model validation, and file-list reference checks. A referenced object that is required to be a particular BIA type must exist in the metadata and have an appropriate type.

For datasets, specimen imaging preparation protocols, image acquisition protocols, annotation methods and signal channels, `@id` must be a relative IRI, such as `#dataset-1` or `protocols/preparation`. Absolute IRIs and blank-node identifiers such as `_:dataset-1` are not accepted for those entities by this profile. Other entities retain the identifier rules of the existing models.

In the tables below, **required** and **recommended** refer to the corresponding checks when an entity of that type is present. Unless specified otherwise, optional properties follow the existing models. References are represented by objects such as `{"@id": "#sample-1"}`; reference collections use the forms supported by the relevant model.

## Study

The single study has `@id` `./` and includes the types `Dataset` and `bia:Study`.

| Property | Requirement | Details |
| --- | --- | --- |
| `name` | Required | Study title. |
| `description` | Required | Description of the study. |
| `license` | Required | Exactly `https://creativecommons.org/publicdomain/zero/1.0/` or `https://creativecommons.org/licenses/by/4.0/`. |
| `datePublished` | Required by the existing model | Uses the existing model's date validation; v0 adds no placeholder rule. |
| `accessionId` | Required by the existing model | Uses the existing model's string validation; v0 adds no placeholder or non-empty constraint. |
| `hasPart` | Required | References all BIA datasets and the file list. |
| `author` | Required | At least one reference to a `bia:Contributor`. |
| `relatedPublication` | Recommended | References to `bia:Publication` entities. |
| `acknowledgement`, `keywords`, `funding`, `seeAlso` | Recommended | Describe acknowledgements, keywords, funding and related resources. |
| `doi` | Optional | A non-null value does not receive an additional v0 warning or error. |

## Datasets

Each dataset includes the types `Dataset` and `bia:Dataset`, has a relative `@id`, and has a `name`. Its `description` is optional.

Each dataset must provide at least one of the following:

1. An `associatedAnnotationMethod` reference; or
2. All three references: `associatedBiologicalEntity`, `associatedSpecimenImagingPreparationProtocol`, and `associatedImageAcquisitionProtocol`.

Both options may be provided. The references must point respectively to `bia:AnnotationMethod`, `bia:BioSample`, `bia:SpecimenImagingPreparationProtocol`, and `bia:ImageAcquisitionProtocol` entities in the metadata. Empty collections do not satisfy a required association.

Every dataset must be referenced by at least one row in the file list. A dataset with an `associatedImageAcquisitionProtocol` must have at least one row **in that dataset** whose type is `http://bia/Image`.

## Other metadata entities

All entities must meet their existing model requirements, including an `@id` and the relevant BIA type. The following table summarizes the submission-specific property checks.

| Entity and type | Required properties | Recommended properties |
| --- | --- | --- |
| Publication, `bia:Publication` | `name` | `doi`, `pubmedId`, `authorNames` |
| Contributor, `bia:Contributor` | `name` in the existing model; also type `Person` or `Organization` | `memberOf` for a person |
| Biosample, `bia:BioSample` | `name`, `description`, `organismClassification` | `experimentalVariableDescription`, `extrinsicVariableDescription`, `intrinsicVariableDescription`, `growthProtocol` |
| Taxon, `bia:Taxon` | `scientificName` | — |
| Specimen imaging preparation protocol, `bia:SpecimenImagingPreparationProtocol` | `name`, `description` | `signalChannelInformation` |
| Signal channel, `bia:SignalChannel` | — | `channelBiologicalEntity`, `signalContrastMechanismDescription`, `channelContentDescription` |
| Image acquisition protocol, `bia:ImageAcquisitionProtocol` | `name`, `description`, `imagingInstrumentDescription`, `imagingMethodName`, `fbbiId` | — |
| Annotation method, `bia:AnnotationMethod` | `name`, `description`, `methodType` | `annotationCriteria`, `annotationCoverage`, `annotationSourceIndicator` |

The model uses `pubmedId` for a publication. `methodType`, `imagingMethodName` and `fbbiId` are lists of strings. The profile requires the latter three lists to be non-empty, but adds no URL-format check for `fbbiId`. Taxon identifiers follow the existing model's IRI validation; this profile does not restrict them to NCBI identifier formats.

`organismClassification` references `bia:Taxon` entities. `signalChannelInformation` references `bia:SignalChannel` entities. When supplied, `growthProtocol` is an object reference to a `bia:Protocol` or a protocol subclass recognized by the bundled ontology. Contributor `memberOf` references an organization or `bia:Affiliation` entity.

## File list

`file_list.tsv` is tab-separated. Its first column must be named either `filepath` or `file_path`. It must also contain `dataset` and `type` columns. Every column in the TSV, including additional columns, must have a `csvw:Column` definition linked through the file list's table schema.

| Column | Required `propertyUrl` in its column definition | Purpose |
| --- | --- | --- |
| `filepath` or `file_path` | `http://bia/filePath` | Relative path or filename of the listed file. |
| `dataset` | `http://schema.org/isPartOf` | Reference to a BIA dataset in the RO-Crate metadata. |
| `type` | `http://www.w3.org/1999/02/22-rdf-syntax-ns#type` | Type of the listed file. |

The `type` value must be one of these **full IRIs**:

| Value | Use |
| --- | --- |
| `http://bia/Image` | Image file, including an image annotation. |
| `http://bia/AnnotationData` | Annotation data that is not an image. |
| `http://bia/File` | Other supporting file. |

The inherited minimal checks include uniqueness of file paths and validation of recognized references to metadata entities and other file-list rows. They check dataset references that are supplied; the additional v0 check ensures that each dataset is represented by at least one row.

### Source images and labels

If any dataset references an annotation method, the TSV must have a column named `source image`, `source_image`, or `associated_source_image`, whose column definition has `propertyUrl` `http://bia/associatedSourceImage`.

When a source-image value is supplied, the inherited reference check resolves it against file paths or labels in the file list. A value may contain a single reference or a bracketed, comma-separated list of references. A missing target, or a target whose type is not `http://bia/Image`, is an error. The profile does not currently infer which rows must contain a source-image value.

A `label` column can group files that together represent an image. Labels do not have to be unique, including across datasets. The existing source-reference lookup is not scoped by dataset: it checks labels before paths and, when labels repeat, uses the last matching label in the file list. Keep that behaviour in mind when choosing source references.

## Scope and deferred checks

- The file list is intended to describe the files in the submission. This validator does **not** compare the list with files on disk; that comparison is performed by another component.
- `methodType` is required, but its controlled-vocabulary membership is not yet checked. `annotationSourceIndicator` is recommended, but its vocabulary membership is not yet checked. The vocabulary values will be added when available.
- The conditional recommendation for a signal-channel `identifier` in multi-channel images is deferred.
- This profile does not add a check that images are represented only in the file list, nor does it infer which annotation rows should contain a source-image value.

## Versioning

`bia-submission-v0` names this set of submission checks. The `minimal` profile remains separately selectable and is the default. Future submission requirements can be introduced under a new versioned profile identifier.
