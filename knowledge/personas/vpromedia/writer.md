# Role: Writer
# Login Email: imail-test+writer@vcreativeinc.com

## Core Responsibilities
- **Scripting**: Views, creates, and edits scripts.
- **Workflow**: Sends to script review and marks writer job as completed.
- **Communication**: Blogs questions specifically to AEs and Production Managers.

## Permissions & Features
- **Enter Requests**: NO
- **Assign POC**: NO
- **View All Spots**: NO (Access only to spots assigned directly to them).
- **Line Editing**: YES (For scripts).

## Code-Specific Notes
- **Role Flag**: `writeflag`.
- **Assignment Logic**: Visible spots are filtered by the existence of a Writer job in `spot_users` matching their `user_id`.
