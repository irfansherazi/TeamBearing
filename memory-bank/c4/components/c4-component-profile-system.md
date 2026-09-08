# C4 Component: Profile System

## Overview
The **Profile System** is the configuration and plugin layer that allows vQA to be tailored to different target applications and user roles. it decouples the core AI engine from application-specific selectors, authentication flows, and domain knowledge.

## Metadata
- **Module**: `backend/profiles/`
- **Primary Tech**: Python (Dataclasses)
- **Component Type**: Service / Configuration Provider
- **Key Files**:
    - `base.py`: Definition of the `AppProfile` and `LocatorStep` base types.
    - `registry.py`: Singleton registry for managing multiple profiles.
    - `vsuite.py`: Reference implementation for the vSuite application.

## Responsibilities
- **Application Configuration**: Encapsulates all vendor-specific details (Auth flows, DOM sync, selectors).
- **Domain Knowledge**: Stores application-specific glossaries and few-shot examples.
- **Role Management**: Defines RBAC permissions and constraints for different user personas.
- **Prompt Identity**: Customizes how the LLM perceives the target application (system instructions).
- **DOM Synchronization**: Defines application-specific "wait for" signals (spinners, panels, root elements).

## Plugin Contract
The `AppProfile` dataclass acts as the core contract. To support a new application, a developer creates a new profile implementation (like `vsuite.py`) and registers it with the `ProfileRegistry`.

## Interfaces
- `ProfileRegistry.get_profile(name)`: Retrieves a registered application profile.
- `AppProfile.login_flow`: Returns the sequence of actions required for authentication.
- `AppProfile.get_prompt_identity()`: Returns the application-specific system prompt segments.

## Dependencies
- **vQA Backend Core**: Resolves the active profile at run start.
- **LangGraph Engine**: Uses profile for login and navigation nodes.
- **Browser Automation**: Uses profile for DOM synchronization and selector fallbacks.
- **Planner**: Uses profile for prompt grounding.
