# Role: Dubber
# LOGIN EMAIL: imail-test+DemoProdDirector@vcreativeinc.com

## Core Responsibilities
- **Quality Control**: Performs quality checks on audio files.
- **Verification**: Verifies files for accuracy and compliance.
- **Automation**: Marks files for "autodub" processing.

## Permissions & Features
- **Enter Requests**: YES
- **View All Spots**: YES
- **Dub**: YES
- **Edit Status**: YES

## Code-Specific Notes
- **Role Flag**: `dubflag`.
- **Autodub Integration**: Uses a specific status or flag to trigger the `autodub` microservice (historically a Java app, potentially migrated to Python).
