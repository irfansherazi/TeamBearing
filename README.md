# vReview

Standalone app for **AI code review** and **memory leak checks** before a PR.

It is not vQA. The dashboard is AI Review + Memory Watch. Review logic and memory sampling live in this repo.

---

## What it does

**AI Review** — pick vsuitePlatform or vcapi, a branch, optional commits, and a base branch. Runs `npm run ai:review` and shows a PASS/FAIL table plus a live log.

**Memory Watch** — pick a user flow (default: Production Orders Quick Order snapshots), env (`local` / `qa` / `test` / `smoke`), and cycle count when the flow repeats. Drives a real Chrome session against the vSuite URL, samples heap via CDP, and shows a PASS/FAIL table plus video. `local` is `http://localhost:4200`.

---

## How repos connect

AI Review does **not** call GitHub for branches. It uses sibling folders on disk:

```
vcreative-apps/
  vReview/           ← this app
  vsuitePlatform/    ← local git clone (must already exist)
  vcapi/             ← local git clone (must already exist)
```

The branch you type must already be on your machine (`git fetch` in that clone).

Memory Watch does **not** need those git folders. It needs a running vSuite environment (default `qa`) and Playwright storage states generated locally.

---

## Local run

Prerequisites: Python 3.12+, Node 20+, a venv with backend deps, `frontend/npm install`.

```powershell
Copy-Item .env.example .env
# set SKIP_SSM=1 for local
.\start.ps1
```

| Service | URL |
|---|---|
| App | http://localhost:5173 |
| API docs | http://localhost:8000/docs |

Stop: `.\start.ps1 -Stop`

macOS / Linux: `./start.sh` / `./start.sh --stop`

---

## Commands

```bash
# AI Review from the terminal (run from vReview/)
npm run ai:review -- --app=platform --branch=Your/Branch --base=Develop
npm run ai:review -- --app=vcapi --branch=Your/Branch --base=develop

# Memory Watch from the terminal
npm run memory:test -- --flow=qo-open-close-snapshot --env=local
```

---

## Do not commit

- `.env` (secrets)
- `.venv/`, `node_modules/`, `frontend/node_modules/`
- Playwright session files (`playwright/storage/`, `storage/*/storageState_*.json`)
- SQLite history (`*.db`)
- Memory Watch reports (`playwright/memory-reports/`)
