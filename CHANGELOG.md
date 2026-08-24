## 0.3.1 (2026-08-24)

### Feat

- **Study**: added fundingStatement field to study model (#9)
- **BIAROCrateMetadata**: Added a function to order to_dict function  (#10)
- **BIAROCrateMetadata**: Added a function to order the dictionary when transforming BIAROCrateMetadata to dict
- **ROCrateModel**: ROCrateModel set to allow extra fields (#12)
- **ROCrateModel**: ROCrateModel set to allow extra fields

### Fix

- **ro-crate-models**: Add RO-Crate CreativeWork to registry
- **study-ro-crate-model**: Updated Study model with fundingStatement field
- **Affiliaton**: Fix typo in Affiliation class name (#11)
- **Affiliaton**: Fix typo in Affiliation class name

### Refactor

- **ro_crate_generator_utils.py**: Remove unused imports (#15)
- **ro_crate_generator_utils.py**: Remove unused imports

## 0.3.0 (2026-06-01)

### Feat

- Updated RO-Crate models to enable round-trip generation of stucturally valid ro-crate-metadata.json documents using the context.

## 0.2.1 (2026-05-22)

- Minor changes to the README

## 0.2.0 (2026-05-21)

### Feat

- Restructure README and pyproject.toml for clarity and completeness
- Update project name and license attribution for clarity
- Implement linked data context and models for BIA ROCrate

### Refactor

- **validation**: move RO-Crate metadata validation and tests in bia-ro-crate (#545)
