# vQA Authentication System

This system implements a production-style authentication flow with support for SSO cookies, App-local tokens, and MFA.

## Features
- **Dual Token Flow**: Uses an SSO cookie for cross-domain/cross-app session persistence and a local App Token for authenticated API requests.
- **MFA Support**: Native support for multi-factor authentication challenges during login.
- **Silent Restore**: Automatically restores the App session using the SSO cookie if the local token is missing or expired.
- **Real Backend Adapters**: Direct integration with `vcapi` for authentication.
- **Periodic Refresh**: Automatically refreshes both SSO and App tokens in the background.

## Flow
1. **Login**: User submits credentials. `vcapi` returns an SSO token.
2. **App Boot**: The `AuthProvider` checks for an App token. If missing, it checks for an SSO cookie. If the cookie exists, it calls `vproLogin` (session exchange) to get a fresh App token without user intervention.
3. **API Calls**: All calls use the App token in the `Authorization: Bearer` header.
4. **Refresh**: Background timers periodically call refresh endpoints to keep both sessions alive.

## Configuration
The system automatically selects the correct endpoint based on the build mode:
- **Development** (`npm run dev`): Uses `frontend/.env.development` -> `https://vcapi-develop.vcreative.net`
- **Production** (`npm run build`): Uses `frontend/.env.production` -> `https://vcapi.vcreative.net`

No manual environment variable configuration is needed for deployment as the build process (triggered by `deploy.sh`) automatically embeds the production values.

### Variables:
- `VITE_VCAPI_URL`: URL of the `vcapi` backend.
- `VITE_SSO_COOKIE_NAME`: Name of the SSO cookie.
- `VITE_COOKIE_DOMAIN`: Domain for the SSO cookie.

## Structure
- `auth/AuthProvider.tsx`: React Context provider managing state.
- `auth/authService.ts`: Orchestrates API calls and storage.
- `auth/authStorage.ts`: Handles cookie and localStorage persistence.
- `auth/authTypes.ts`: Centralized interfaces and types (including `AuthApi` interface).
- `auth/realAuthApi.ts`: implementation for `vcapi` calls.
