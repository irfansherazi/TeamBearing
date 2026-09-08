## Mandates
### General Coding Practices

- **Never leave empty/open `catch` blocks.** All exceptions and errors must be explicitly logged or appropriately handled. If an AI assistant cannot determine the correct action to take inside a `catch` block, it MUST stop and explicitly ask the user for guidance rather than silently swallowing the error.

### Logging Convention

- **Never use `console.log/warn/error` inside NestJS services or controllers.** `console.*` is only acceptable in non-NestJS scripts (plain Node.js CLI tools, migration scripts, etc.).
- **Always use `request.emit('addLog', message)` for logging inside NestJS services.** This emits logs through the `AppLoggerMiddleware` pipeline so they surface in real-time to the frontend.
- **Thread the `request` object down through private helpers.** If a private method needs to log, add `request?: Request` as a parameter and call it with `request?.emit(...)`. Never use `console.*` as a fallback inside a helper that could receive a request.
- **For RabbitMQ consumers and other background/queue contexts** where no real HTTP request object exists, import and use `fakeRequest` from `src/app.service.util`. The `fakeRequest` is a live `EventEmitter` that already has `AppLoggerMiddleware` attached at startup. Pass it as the `request` argument to any service method that accepts one (e.g. `processNaturalLanguage(dto, fakeRequest as any)`).
- **NestJS `Logger` (`this.logger`) is also not the team convention** and must not be used in this module. Use `request.emit` / `fakeRequest.emit` exclusively.

### Git Branching

- **Always use `--no-track` when creating feature branches from a base branch.** Using `git checkout -b newbranch origin/master` (or `origin/develop`) sets the upstream tracking to the base branch, which causes `git push` to push directly to master/develop instead of the new branch. This has caused accidental pushes to protected branches.
  - ✅ **Correct:** `git checkout -b chrisf/my-feature --no-track origin/master`
  - ❌ **Wrong:** `git checkout -b chrisf/my-feature origin/master`
- **Always use `-u` when pushing a new branch for the first time** to set the tracking to the correct remote branch.
  - ✅ **Correct:** `git push -u origin chrisf/my-feature`
  - ❌ **Wrong:** `git push origin chrisf/my-feature` (without `-u`, tracking may still point to the base branch)

### Testing Convention

- **Never use `npx jest` directly.** Always use `npm test` to run tests.
- **To run a specific spec file**, pass a partial match after `npm test`. The match is applied to the file path, so any unique substring works.
  - ✅ **Run all tests:** `npm test`
  - ✅ **Run one controller's tests:** `npm test common-tpi.controller`
  - ✅ **Partial match also works:** `npm test spot-search`
  - ❌ **Wrong:** `npx jest --testPathPattern=common-tpi.controller.spec`
