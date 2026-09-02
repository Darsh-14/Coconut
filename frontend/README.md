# Recourse frontend

The reviewer interface for Recourse: dispute queue, evidence-to-verdict inspection,
representment editing, append-only human actions, evaluation metrics, and the public landing
page. It is a React 19 + TypeScript application built with Vite and Tailwind CSS.

## Run locally

Start the API first from `backend/`:

```powershell
..\.venv\Scripts\uvicorn.exe app.main:app --reload --port 8000
```

Then start this application from `frontend/`:

```powershell
npm install
npm run dev
```

Open <http://localhost:5173>. Vite proxies `/api` requests to the backend on port 8000.
The sign-in screen is intentionally a demo-only client-side gate; it is not authentication.

## Checks

```powershell
npm run lint
npm run build
```

The optional browser checks require both servers and Playwright's Chromium binary:

```powershell
npx playwright install chromium
npm run verify:ui
```

`verify:landing`, `verify:a11y`, and `verify:smoke` can also be run separately.
