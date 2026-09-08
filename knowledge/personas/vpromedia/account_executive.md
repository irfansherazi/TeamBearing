# Role: Account Executive (AE)
# LOGIN EMAIL: imail-test+DemoAE@vcreativeinc.com

## Core Responsibilities
- **Order Creation**: Primary creator of Quick Orders (QO).
- **Draft Management**: Saves and manages own drafts.
- **Communication**: Answers blog questions from Production and Creative teams.
- **Approval**: Approves scripts and final spots.
- **Client Interaction**: Sends emails to clients for review and approval.
- **Revisions**: Manages revision requests.

## Permissions & Features
- **Enter Requests**: YES
- **View All Spots**: NO (Off by default, can be toggled).
- **Manage Clients**: Own clients only.
- **Script Visibility**: Shows only if "Needs Producing" is selected.
- **Edit Status**: YES

## Code-Specific Notes
- **POC Logic**: When an AE creates a spot, they are typically added to the `spot_users` list, making them a Point of Contact (POC) for that request.
- **Search**: Search on other users' requests is OFF by default.
