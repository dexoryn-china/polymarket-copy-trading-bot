# Polymarket Copy Bot dashboard

React 19 + TypeScript + Vite + Tailwind CSS v4 web UI for Polymarket Copy Bot.

## Develop

```powershell
cd ui
npm install
npm run dev        # http://localhost:5173, proxies /api (incl. websocket) to http://127.0.0.1:8787
```

Start the Python backend first so the proxy has something to talk to.

### Without the backend

```powershell
npm run dev:mock
```

Runs Vite in `mock` mode (`.env.mock` sets `VITE_MOCK=1`). `src/api/mock.ts` intercepts `fetch('/api/…')`
and the `/api/ws` websocket with in-memory fixtures and simulated live activity. The mock is loaded via
dynamic import only in that mode and is not included in production builds.

## Build

```powershell
npm run build      # tsc -b && vite build → ../app/web/static
npm run preview    # serve the built bundle locally
npm run lint       # type-check only
```

The backend serves `app/web/static/` and should fall back to `index.html` for unknown non-`/api` paths
so client-side routes (`/targets`, `/positions`, …) work on reload.

## Auth

If any API call returns 401, the UI prompts for a token, stores it in `localStorage` (`copybot.token`)
and sends it as `Authorization: Bearer <token>` and as `?token=` on the websocket URL. It can also be
set or cleared on the Settings page.
