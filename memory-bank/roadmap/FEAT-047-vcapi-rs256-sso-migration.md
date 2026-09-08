---
legacy_id: FEAT-047
version: next
linked_tasks: [vcapi-rs256-sso-migration]
status: in_progress
---

### FEAT-047: vcAPI RS256 SSO Migration
- **Version**: next
- **Status**: in-progress
- **Priority**: high
- **Complexity**: Level 3
- **Description**: Migrate vQA from its local HS256-based authentication to vcAPI's RS256-based SSO system. This enables single sign-on across the vProMedia ecosystem. Key components: (1) Backend RS256 JWT validation using vcAPI's public key; (2) Alignment with vcAPI's SsoToken structure; (3) Frontend AuthContext and LoginPage integration with vcAPI; (4) Deprecation of local SQLite user database.
- **Linked Tasks**: vcapi-rs256-sso-migration
- **Branch**: feature/FEAT-047-sso-migration
- **Created**: 2026-05-26
