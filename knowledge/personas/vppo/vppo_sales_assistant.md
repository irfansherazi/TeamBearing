# Role: Sales Assistant
# LOGIN EMAIL: imail-test+SalesAssistant@vcreativeinc.com

## Core Responsibilities
- **All AE Abilities**: Can enter requests on behalf of an AE.
- **Spot Management**: Can view all AE spots for the firm.

## Permissions & Features
- **Enter Requests**: YES (On behalf of AE).
- **View All Spots**: YES (Overview of all production activity).
- **Assign POC**: NO
- **Production Abilities**: NO (Unless specifically granted).

## Code-Specific Notes
- **On Behalf Of**: When creating orders, the user_id in the payload might be the AE's ID while the actual_user_id tracks the assistant.
