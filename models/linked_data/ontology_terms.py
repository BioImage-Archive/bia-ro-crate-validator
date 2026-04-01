from rdflib.namespace import DefinedNamespace, Namespace
from rdflib.term import URIRef


class SCHEMA(DefinedNamespace):
    # Classes
    CreativeWork: URIRef
    Dataset: URIRef
    Organization: URIRef
    Person: URIRef
    ScholarlyArticle: URIRef

    # Properties
    address: URIRef
    additionalType: URIRef
    affiliation: URIRef
    author: URIRef
    datePublished: URIRef
    description: URIRef
    email: URIRef
    hasPart: URIRef
    identifier: URIRef
    isPartOf: URIRef
    keywords: URIRef
    license: URIRef
    memberOf: URIRef
    name: URIRef
    taxonomicRange: URIRef
    url: URIRef

    _NS = Namespace("http://schema.org/")


class DUBLINCORE(DefinedNamespace):
    # Properties
    identifier: URIRef
    hasFormat: URIRef
    conformsTo: URIRef

    _NS = Namespace("http://purl.org/dc/terms/")


class DARWINCORE(DefinedNamespace):
    # Properties
    scientificName: URIRef
    vernacularName: URIRef

    _NS = Namespace("http://rs.tdwg.org/dwc/terms/")


class DARWINCOREIRI(DefinedNamespace):
    # Properties
    measurementMethod: URIRef

    _NS = Namespace("http://rs.tdwg.org/dwc/iri/")


class CSVW(DefinedNamespace):
    # Classes
    Column: URIRef
    Schema: URIRef

    # Properties
    column: URIRef
    name: URIRef
    propertyUrl: URIRef
    tableSchema: URIRef

    _NS = Namespace("http://www.w3.org/ns/csvw#")


class BIA(DefinedNamespace):
    # Classes
    Affiliation: URIRef
    AnnotationData: URIRef
    AnnotationMethod: URIRef
    BioSample: URIRef
    Contributor: URIRef
    CreationProcess: URIRef
    Dataset: URIRef
    ExternalReference: URIRef
    FileList: URIRef
    FundingBody: URIRef
    Grant: URIRef
    Image: URIRef
    ImageAcquisitionProtocol: URIRef
    ImageAnalysisMethod: URIRef
    ImageCorrelationMethod: URIRef
    Protocol: URIRef
    Publication: URIRef
    SignalChannel: URIRef
    Specimen: URIRef
    SpecimenImagingPreparationProtocol: URIRef
    Study: URIRef
    Taxon: URIRef

    # Properties
    acknowledgement: URIRef
    annotationCoverage: URIRef
    annotationCriteria: URIRef
    annotationMethod: URIRef
    annotationMethodType: URIRef
    annotationSourceIndicator: URIRef
    associatedAnalysisMethod: URIRef
    associatedAnnotationMethod: URIRef
    associatedBiologicalEntity: URIRef
    associatedCorrelationMethod: URIRef
    associatedCreationProcess: URIRef
    associatedImageAcquisitionProtocol: URIRef
    associatedImagingPreparationProtocol: URIRef
    associatedProtocol: URIRef
    associatedSourceImage: URIRef
    associatedSubject: URIRef
    authorNames: URIRef
    biologicalEntityDescription: URIRef
    channelBiologicalEntity: URIRef
    channelContentDescription: URIRef
    experimentalVariableDescription: URIRef
    extrinsicVariableDescription: URIRef
    fbbiId: URIRef
    featuresAnalysed: URIRef
    fiducialsUsed: URIRef
    filePath: URIRef
    growthProtocol: URIRef
    imageAcquisitionProtocol: URIRef
    imagingInstrumentDescription: URIRef
    imagingMethodName: URIRef
    imagingPreparationProtocol: URIRef
    inputImage: URIRef
    intrinsicVariableDescription: URIRef
    protocol: URIRef
    relatedPublication: URIRef
    resultOf: URIRef
    role: URIRef
    sampleOf: URIRef
    signalChannelInformation: URIRef
    signalContrastMechanismDescription: URIRef
    sizeInBytes: URIRef
    spatialInformation: URIRef
    subject: URIRef
    transformationDescription: URIRef
    transformationMatrix: URIRef
    uri: URIRef
    website: URIRef
    xIndex: URIRef
    yIndex: URIRef
    zIndex: URIRef
    tIndex: URIRef
    cIndex: URIRef

    _NS = Namespace("http://bia/")
