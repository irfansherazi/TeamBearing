# Role: Production Manager
# Login Email: imail-test+DemoProdMan@vcreativeinc.com

## Core Responsibilities
- **Delegation**: Delegates jobs and resources to requests.
- **Communication**: Writes blogs to coordinate between Sales and Creative.
- **Creative Work**: Writes and edits scripts.
- **Management**: Changes statuses, adds production costs, and logs time.
- **Oversight**: Full overview of all production activity in the firm.
- **Administrative**: Able to approve/reject new clients and requests. Eventually a Local Admin.

## Permissions & Features
- **Enter Requests**: YES (On behalf of AE).
- **Assign POC**: YES
- **View All Spots**: YES
- **Assign Cart/House Numbers**: YES
- **Edit Status**: YES
- **Dub**: YES
- **Line Editing**: YES

## Code-Specific Notes
- **Adility Flags**: Often check for `produceflag` and `masterflag` (admin).
- **Delegation Logic**: Interacts with `SpotUser` to assign roles like Writer, Producer, and Voicer.
