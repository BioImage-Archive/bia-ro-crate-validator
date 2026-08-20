from warnings import warn

from pydantic import AnyUrl, BaseModel, ConfigDict, Field, field_validator
from rdflib import RDFS
from typing_extensions import Annotated, Optional

from bia_ro_crate.models.linked_data.ontology_terms import (
    BIA,
    CSVW,
    DARWINCORE,
    SCHEMA,
)
from bia_ro_crate.models.linked_data.pydantic_ld.FieldContext import FieldContext
from bia_ro_crate.models.linked_data.pydantic_ld.LDModel import ObjectReference
from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel
from bia_ro_crate.models.model_registry import register_ro_crate_class


class ROCrateCreativeWork(ROCrateModel):
    id: str = Field(alias="@id", default="ro-crate-metadata.json")
    type: str | list[str] = Field(alias="@type", default="CreativeWork")
    conformsTo: dict = Field(default={"@id": "https://w3id.org/ro/crate/1.1"})
    about: dict = Field(default={"@id": "./"})

    model_config = ConfigDict(model_type=SCHEMA.CreativeWork)


# Studies and Publications


@register_ro_crate_class
class Study(ROCrateModel):
    name: Annotated[str, FieldContext(SCHEMA.name)] = Field()
    author: Annotated[
        list[ObjectReference],
        FieldContext(SCHEMA.author, is_id_field=True, container="@set"),
    ] = Field(min_length=1)
    description: Annotated[str, FieldContext(SCHEMA.description)] = Field()
    license: Annotated[AnyUrl, FieldContext(SCHEMA.license)] = Field()
    datePublished: Annotated[str, FieldContext(SCHEMA.datePublished)] = Field()
    keywords: Annotated[list[str], FieldContext(SCHEMA.keywords, container="@set")] = (
        Field(default_factory=list)
    )
    acknowledgement: Annotated[Optional[str], FieldContext(BIA.acknowledgement)] = (
        Field(default=None)
    )
    hasPart: Annotated[
        list[ObjectReference],
        FieldContext(SCHEMA.hasPart, is_id_field=True, container="@set"),
    ] = Field()
    accessionId: Annotated[str, FieldContext(BIA.accessionId)] = Field()
    doi: Annotated[str | None, FieldContext(BIA.doi)] = Field(default=None)
    seeAlso: Annotated[
        list[ObjectReference], FieldContext(RDFS.seeAlso, container="@set")
    ] = Field(default_factory=list)
    relatedPublication: Annotated[
        list[ObjectReference],
        FieldContext(BIA.relatedPublication, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)
    funding: Annotated[
        list[ObjectReference], FieldContext(SCHEMA.funding, container="@set")
    ] = Field(default_factory=list)

    model_config = ConfigDict(model_type=BIA.Study)

    @field_validator("id", mode="after")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if value != "./":
            raise ValueError("Study id should be root ro-crate entity.")
        return value


@register_ro_crate_class
class Publication(ROCrateModel):
    name: Annotated[Optional[str], FieldContext(SCHEMA.name)] = Field(default=None)
    authorNames: Annotated[Optional[str], FieldContext(BIA.authorNames)] = Field(
        default=None
    )
    yearPublished: Annotated[Optional[int], FieldContext(BIA.yearPublished)] = Field(
        default=None
    )
    pubmedId: Annotated[Optional[str], FieldContext(BIA.pubmedId)] = Field(default=None)
    doi: Annotated[Optional[str], FieldContext(BIA.doi)] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.Publication)


# Contributors and Affiliations


@register_ro_crate_class
class Contributor(ROCrateModel):
    name: Annotated[str, FieldContext(SCHEMA.name)] = Field()
    address: Annotated[Optional[str], FieldContext(SCHEMA.address)] = Field(
        default=None
    )
    website: Annotated[Optional[AnyUrl], FieldContext(BIA.website)] = Field(
        default=None
    )
    memberOf: Annotated[
        list[ObjectReference],
        FieldContext(SCHEMA.memberOf, container="@set"),
    ] = Field(default_factory=list)
    role: Annotated[list[str], FieldContext(BIA.role, container="@set")] = Field(
        default_factory=list
    )
    email: Annotated[Optional[str], FieldContext(SCHEMA.email)] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.Contributor)


@register_ro_crate_class
class Affiliation(ROCrateModel):
    name: Annotated[str, FieldContext(SCHEMA.name)] = Field()
    address: Annotated[Optional[str], FieldContext(SCHEMA.address)] = Field(
        default=None
    )
    website: Annotated[Optional[AnyUrl], FieldContext(BIA.website)] = Field(
        default=None
    )

    model_config = ConfigDict(model_type=BIA.Affiliation)


# Old class with typo in name.
class Affiliaton(Affiliation):
    def __init__(self, *args, **kwargs):
        warn(
            "'Affiliaton' is deprecated and will be removed in v1.0. "
            "Use 'Affiliation' instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(*args, **kwargs)


# Grants and funding


@register_ro_crate_class
class Grant(ROCrateModel):
    funder: Annotated[
        list[ObjectReference], FieldContext(SCHEMA.funder, container="@set")
    ] = Field()
    name: Annotated[Optional[str], FieldContext(SCHEMA.name)] = Field(default=None)
    identifier: Annotated[Optional[str], FieldContext(SCHEMA.identifier)] = Field(
        default=None
    )

    model_config = ConfigDict(model_type=BIA.Grant)


@register_ro_crate_class
class FundingBody(ROCrateModel):
    name: Annotated[Optional[str], FieldContext(SCHEMA.name)] = Field(default=None)
    identifier: Annotated[Optional[str], FieldContext(SCHEMA.identifier)] = Field(
        default=None
    )

    model_config = ConfigDict(model_type=BIA.FundingBody)


# External References


@register_ro_crate_class
class ExternalReference(ROCrateModel):
    description: Annotated[Optional[str], FieldContext(SCHEMA.description)] = Field(
        default=None
    )
    additionalType: Annotated[Optional[str], FieldContext(SCHEMA.additionalType)] = (
        Field(default=None)
    )

    model_config = ConfigDict(model_type=BIA.ExternalReference)


# Datasets and associations?


@register_ro_crate_class
class Dataset(ROCrateModel):
    name: Annotated[str, FieldContext(SCHEMA.name)] = Field()
    description: Annotated[Optional[str], FieldContext(SCHEMA.description)] = Field(
        default=None
    )

    associatedBiologicalEntity: Annotated[
        list[ObjectReference],
        FieldContext(
            BIA.associatedBiologicalEntity, is_id_field=True, container="@set"
        ),
    ] = Field(default_factory=list)

    associatedSpecimenImagingPreparationProtocol: Annotated[
        list[ObjectReference],
        FieldContext(
            BIA.associatedImagingPreparationProtocol, is_id_field=True, container="@set"
        ),
    ] = Field(default_factory=list)

    associatedSpecimen: Annotated[
        Optional[ObjectReference],
        FieldContext(BIA.associatedSubject, is_id_field=True),
    ] = Field(default=None)

    associatedCreationProcess: Annotated[
        Optional[ObjectReference],
        FieldContext(BIA.associatedCreationProcess, is_id_field=True),
    ] = Field(default=None)

    associatedSourceImage: Annotated[
        list[ObjectReference],
        FieldContext(BIA.associatedSourceImage, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)

    associatedImageAcquisitionProtocol: Annotated[
        list[ObjectReference],
        FieldContext(
            BIA.associatedImageAcquisitionProtocol, is_id_field=True, container="@set"
        ),
    ] = Field(default_factory=list)

    associatedAnnotationMethod: Annotated[
        list[ObjectReference],
        FieldContext(
            BIA.associatedAnnotationMethod, is_id_field=True, container="@set"
        ),
    ] = Field(default_factory=list)

    associatedImageAnalysisMethod: Annotated[
        list[ObjectReference],
        FieldContext(BIA.associatedAnalysisMethod, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)

    associatedImageCorrelationMethod: Annotated[
        list[ObjectReference],
        FieldContext(
            BIA.associatedCorrelationMethod, is_id_field=True, container="@set"
        ),
    ] = Field(default_factory=list)

    associatedProtocol: Annotated[
        list[ObjectReference],
        FieldContext(BIA.associatedProtocol, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)

    model_config = ConfigDict(model_type=BIA.Dataset)


# File List


@register_ro_crate_class
class FileList(ROCrateModel):
    tableSchema: Annotated[
        ObjectReference,
        FieldContext(CSVW.tableSchema, is_id_field=True),
    ] = Field()

    model_config = ConfigDict(model_type=BIA.FileList)


@register_ro_crate_class
class TableSchema(ROCrateModel):
    column: Annotated[
        list[ObjectReference],
        FieldContext(CSVW.column, is_id_field=True, container="@set"),
    ] = Field(min_length=1)

    model_config = ConfigDict(model_type=CSVW.Schema)


@register_ro_crate_class
class Column(ROCrateModel):
    columnName: Annotated[str, FieldContext(CSVW.name)] = Field()
    propertyUrl: Annotated[Optional[str], FieldContext(CSVW.propertyUrl)] = Field(
        default=None
    )

    model_config = ConfigDict(model_type=CSVW.Column)


# Images and AnnotationData


@register_ro_crate_class
class Image(ROCrateModel):
    resultOf: Annotated[
        ObjectReference, FieldContext(BIA.resultOf, is_id_field=True)
    ] = Field(default=None)
    name: Annotated[Optional[str], FieldContext(SCHEMA.name)] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.Image)


@register_ro_crate_class
class AnnotationData(ROCrateModel):
    resultOf: Annotated[
        ObjectReference, FieldContext(BIA.resultOf, is_id_field=True)
    ] = Field(default=None)
    name: Annotated[Optional[str], FieldContext(SCHEMA.name)] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.AnnotationData)


# Specimen and CreationProcess


@register_ro_crate_class
class Specimen(ROCrateModel):
    biologicalEntity: Annotated[
        list[ObjectReference],
        FieldContext(BIA.sampleOf, is_id_field=True, container="@set"),
    ] = Field(min_length=1)
    imagingPreparationProtocol: Annotated[
        list[ObjectReference],
        FieldContext(
            BIA.imagingPreparationProtocol, is_id_field=True, container="@set"
        ),
    ] = Field(min_length=1)

    model_config = ConfigDict(model_type=BIA.Specimen)


@register_ro_crate_class
class CreationProcess(ROCrateModel):
    imageAcquisitionProtocol: Annotated[
        list[ObjectReference],
        FieldContext(BIA.imageAcquisitionProtocol, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)
    subject: Annotated[
        Optional[ObjectReference], FieldContext(BIA.subject, is_id_field=True)
    ] = Field(default=None)
    protocol: Annotated[
        list[ObjectReference],
        FieldContext(BIA.protocol, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)
    annotationMethod: Annotated[
        list[ObjectReference],
        FieldContext(BIA.annotationMethod, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)
    inputImage: Annotated[
        list[ObjectReference],
        FieldContext(BIA.inputImage, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)

    model_config = ConfigDict(model_type=BIA.CreationProcess)


# BioSample and Taxon


@register_ro_crate_class
class BioSample(ROCrateModel):
    name: Annotated[Optional[str], FieldContext(SCHEMA.name)] = Field(default=None)
    description: Annotated[str, FieldContext(SCHEMA.description)] = Field()
    experimentalVariableDescription: Annotated[
        list[str], FieldContext(BIA.experimentalVariableDescription, container="@set")
    ] = Field(default_factory=list)
    extrinsicVariableDescription: Annotated[
        list[str], FieldContext(BIA.extrinsicVariableDescription, container="@set")
    ] = Field(default_factory=list)
    intrinsicVariableDescription: Annotated[
        list[str], FieldContext(BIA.intrinsicVariableDescription, container="@set")
    ] = Field(default_factory=list)
    organismClassification: Annotated[
        list[ObjectReference], FieldContext(SCHEMA.taxonomicRange, container="@set")
    ] = Field(default_factory=list)
    growthProtocol: Annotated[
        Optional[ObjectReference], FieldContext(BIA.growthProtocol, is_id_field=True)
    ] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.BioSample)


@register_ro_crate_class
class Taxon(ROCrateModel):
    commonName: Annotated[Optional[str], FieldContext(DARWINCORE.vernacularName)] = (
        Field(default=None)
    )
    scientificName: Annotated[
        Optional[str], FieldContext(DARWINCORE.scientificName)
    ] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.Taxon)


# Protocols


class ProtocolMixin(BaseModel):
    name: Annotated[Optional[str], FieldContext(SCHEMA.name)] = Field()
    description: Annotated[str, FieldContext(SCHEMA.description)] = Field()


@register_ro_crate_class
class Protocol(ProtocolMixin, ROCrateModel):
    model_config = ConfigDict(model_type=BIA.Protocol)


@register_ro_crate_class
class SpecimenImagingPreparationProtocol(ProtocolMixin, ROCrateModel):
    signalChannelInformation: Annotated[
        list[ObjectReference],
        FieldContext(BIA.signalChannelInformation, is_id_field=True, container="@set"),
    ] = Field(default_factory=list)

    model_config = ConfigDict(model_type=BIA.SpecimenImagingPreparationProtocol)


@register_ro_crate_class
class SignalChannelInformation(ROCrateModel):
    signalContrastMechanismDescription: Annotated[
        Optional[str], FieldContext(BIA.signalContrastMechanismDescription)
    ] = Field(default=None)
    channelContentDescription: Annotated[
        Optional[str], FieldContext(BIA.channelContentDescription)
    ] = Field(default=None)
    channelBiologicalEntity: Annotated[
        Optional[str], FieldContext(BIA.channelBiologicalEntity)
    ] = Field(default=None)
    identifier: Annotated[Optional[str], FieldContext(SCHEMA.identifier)] = Field(
        default=None
    )

    model_config = ConfigDict(model_type=BIA.SignalChannel)


@register_ro_crate_class
class ImageAcquisitionProtocol(ProtocolMixin, ROCrateModel):
    imagingInstrumentDescription: Annotated[
        str, FieldContext(BIA.imagingInstrumentDescription)
    ] = Field()
    imagingMethodName: Annotated[
        list[str], FieldContext(BIA.imagingMethodName, container="@set")
    ] = Field(default_factory=list)
    fbbiId: Annotated[list[str], FieldContext(BIA.fbbiId, container="@set")] = Field(
        default_factory=list
    )

    model_config = ConfigDict(model_type=BIA.ImageAcquisitionProtocol)


@register_ro_crate_class
class AnnotationMethod(ProtocolMixin, ROCrateModel):
    annotationCriteria: Annotated[
        Optional[str], FieldContext(BIA.annotationCriteria)
    ] = Field(default=None)
    annotationCoverage: Annotated[
        Optional[str], FieldContext(BIA.annotationCoverage)
    ] = Field(default=None)
    transformationDescription: Annotated[
        Optional[str], FieldContext(BIA.transformationDescription)
    ] = Field(default=None)
    spatialInformation: Annotated[
        Optional[str], FieldContext(BIA.spatialInformation)
    ] = Field(default=None)
    methodType: Annotated[
        list[str], FieldContext(BIA.annotationMethodType, container="@set")
    ] = Field(default_factory=list)
    annotationSourceIndicator: Annotated[
        Optional[str], FieldContext(BIA.annotationSourceIndicator)
    ] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.AnnotationMethod)


@register_ro_crate_class
class ImageAnalysisMethod(ProtocolMixin, ROCrateModel):
    featuresAnalysed: Annotated[Optional[str], FieldContext(BIA.featuresAnalysed)] = (
        Field(default=None)
    )

    model_config = ConfigDict(model_type=BIA.ImageAnalysisMethod)


@register_ro_crate_class
class ImageCorrelationMethod(ProtocolMixin, ROCrateModel):
    fiducialsUsed: Annotated[Optional[str], FieldContext(BIA.fiducialsUsed)] = Field(
        default=None
    )
    transformationMatrix: Annotated[
        Optional[str], FieldContext(BIA.transformationMatrix)
    ] = Field(default=None)

    model_config = ConfigDict(model_type=BIA.ImageCorrelationMethod)
