import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Set;

import org.eclipse.rdf4j.rio.RDFFormat;
import org.eclipse.rdf4j.rio.RDFParser;
import org.eclipse.rdf4j.rio.Rio;
import org.eclipse.rdf4j.rio.helpers.BasicParserSettings;
import org.semanticweb.HermiT.ReasonerFactory;
import org.semanticweb.owlapi.apibinding.OWLManager;
import org.semanticweb.owlapi.formats.RioRDFDocumentFormat;
import org.semanticweb.owlapi.formats.RioTurtleDocumentFormat;
import org.semanticweb.owlapi.formats.RioTurtleDocumentFormatFactory;
import org.semanticweb.owlapi.formats.TurtleDocumentFormat;
import org.semanticweb.owlapi.io.FileDocumentSource;
import org.semanticweb.owlapi.io.OWLParser;
import org.semanticweb.owlapi.io.RDFParserMetaData;
import org.semanticweb.owlapi.io.RDFResourceParseError;
import org.semanticweb.owlapi.model.OWLOntology;
import org.semanticweb.owlapi.model.OWLOntologyLoaderConfiguration;
import org.semanticweb.owlapi.model.OWLOntologyManager;
import org.semanticweb.owlapi.profiles.OWL2DLProfile;
import org.semanticweb.owlapi.profiles.OWLProfileReport;
import org.semanticweb.owlapi.reasoner.OWLReasoner;
import org.semanticweb.owlapi.rio.RioParserImpl;
import org.semanticweb.owlapi.rio.RioTurtleParserFactory;

/** Check raw RDF literals, OWL parsing, DL profile and HermiT semantics. */
final class CheckOntology {
    public static void main(String[] args) throws Exception {
        Path input = Path.of(args[0]);
        String stage = args[1];
        Path output = Path.of(args[2]);
        if (stage.equals("literals")) {
            RDFParser parser = Rio.createParser(RDFFormat.TURTLE);
            parser.getParserConfig().set(BasicParserSettings.VERIFY_DATATYPE_VALUES, true);
            parser.getParserConfig().set(BasicParserSettings.VERIFY_LANGUAGE_TAGS, true);
            parser.getParserConfig().set(BasicParserSettings.NORMALIZE_DATATYPE_VALUES, false);
            try (InputStream stream = Files.newInputStream(input)) {
                parser.parse(stream, input.toUri().toString());
            }
            System.out.println("Raw Turtle literal validation passed.");
            return;
        }
        if (!stage.equals("profile") && !stage.equals("reason")) {
            throw new IllegalArgumentException("Unknown check: " + stage);
        }
        OWLOntologyManager manager = OWLManager.createOWLOntologyManager();
        // A parse error must stop loading, not become a fresh error class.
        manager.setOntologyParsers(Set.of(new RioTurtleParserFactory() {
            @Override
            public OWLParser createParser() {
                return new RioParserImpl(new RioTurtleDocumentFormatFactory() {
                    @Override
                    public RioRDFDocumentFormat createFormat() {
                        return new CheckedTurtleFormat();
                    }
                });
            }
        }));
        manager.getIRIMappers().clear();
        // Imports are rejected in Python; forbid resolution here as well.
        manager.getIRIMappers().add(iri -> {
            throw new IllegalArgumentException("Unpinned import: " + iri);
        });
        // OWLAPI's strict RDF mode rejects valid anonymous restrictions. Inspect
        // dropped triples explicitly instead, and never repair property punning.
        OWLOntologyLoaderConfiguration config = new OWLOntologyLoaderConfiguration()
            .setStrict(false).setRepairIllegalPunnings(false);
        OWLOntology ontology = manager.loadOntologyFromOntologyDocument(
            new FileDocumentSource(input.toFile(), new TurtleDocumentFormat()), config);
        Object metadata = manager.getOntologyFormat(ontology).getOntologyLoaderMetaData();
        if (!(metadata instanceof RDFParserMetaData rdf)) {
            throw new IllegalStateException("Missing RDF parser evidence");
        }
        if (!rdf.getUnparsedTriples().isEmpty()) {
            throw new IllegalArgumentException(
                "Triples could not be parsed: " + rdf.getUnparsedTriples());
        }
        OWLProfileReport profile = new OWL2DLProfile().checkOntology(ontology);
        if (stage.equals("profile")) {
            Files.writeString(output.resolve("profile.txt"), profile.toString());
        }
        if (!profile.isInProfile()) {
            throw new IllegalArgumentException("OWL 2 DL profile violations: " + profile);
        }
        if (stage.equals("profile")) {
            return;
        }
        OWLReasoner reasoner = new ReasonerFactory().createReasoner(ontology);
        try {
            if (!reasoner.isConsistent()) {
                throw new IllegalArgumentException("Ontology is inconsistent");
            }
            var unsatisfiable = reasoner.getUnsatisfiableClasses().getEntitiesMinusBottom();
            if (!unsatisfiable.isEmpty()) {
                throw new IllegalArgumentException("Unsatisfiable named classes: " + unsatisfiable);
            }
            Files.writeString(output.resolve("reason.txt"),
                "HermiT: consistent; no unsatisfiable named classes.\n");
        } finally {
            reasoner.dispose();
        }
    }

    private static final class CheckedTurtleFormat extends RioTurtleDocumentFormat {
        @Override
        public void addError(RDFResourceParseError error) {
            throw new IllegalArgumentException(
                "OWL parsing error: " + error.getMainNodeTriples());
        }
    }
}
