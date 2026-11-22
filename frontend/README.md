# BedSynth AI Frontend

BedSynth AI's frontend provides the browser interface for configuring hospital operations, generating synthetic datasets, and reviewing owned datasets and analytics. It requires the FastAPI backend for authentication, hospital data, generation, validation, analytics, and exports.

## Technology

- Next.js 15 App Router and React 19
- TypeScript
- Tailwind CSS
- Recharts for charts
- Lucide React for icons
- Framer Motion for interface motion

## Structure and routes

```text
src/
├── app/            # App Router pages, global styles, and page-level tests
├── components/     # Shared application shell and landing page
└── lib/            # Role-routing helpers and tests
```

The shared application shell provides persistent role-based navigation and responsive mobile navigation. Administrators see Hospital Management, Generate Dataset, My Datasets, Analytics, and My Account. Normal users see Dashboard, Generate Dataset, My Datasets, Analytics, Data Validation, and My Account.

| Route | Purpose | Access |
| --- | --- | --- |
| `/` | Public landing page or signed-in user dashboard | Public and normal users; administrators are directed to Hospital Management |
| `/login` | Sign in | Public |
| `/register` | Create a normal user account | Public |
| `/hospitals` | Manage hospitals, departments, beds, and publication | Administrators |
| `/generate` | Configure, preview, and confirm synthetic dataset generation | Signed-in users and administrators |
| `/datasets` | View and manage datasets owned by the signed-in account | Signed-in users and administrators |
| `/datasets/[runId]` | Dataset details, previews, validation history, and exports | Owner only |
| `/analytics` | Run analytics and compatible run comparisons | Signed-in users and administrators |
| `/validation` | Run and review data validation reports | Normal users |
| `/settings` | Account profile, security and sessions, data privacy, and application information | Signed-in users and administrators |

Administrators can configure and publish hospitals. Normal users can select active published hospitals and cannot edit hospital configuration. Dataset routes show only the signed-in account's own runs, including for administrators. Protected route checks in the frontend complement backend authorization; the backend remains authoritative.

## Setup

Use Windows PowerShell from the repository root:

```powershell
Set-Location .\frontend
npm install
if (-not (Test-Path .env.local)) { Copy-Item .env.example .env.local }
```

The recommended setup uses the Next.js same-origin proxy: `BACKEND_API_URL` is a server-side environment variable that points to the backend origin, and the frontend proxies `/api/*` and `/health`. In development it defaults to `http://127.0.0.1:8000`. In production it is required and the build fails if it is missing. Leave `NEXT_PUBLIC_API_BASE_URL` blank to use the proxy. This optional browser-visible variable can point directly to an API origin, but direct cross-site cookie requests require additional backend cookie configuration. Never put secrets in `NEXT_PUBLIC_*` variables. Do not overwrite an existing `.env.local` file.

## Run

Start the backend in a separate terminal first, using the backend setup in the [root README](../README.md) or [backend README](../backend/README.md). Then, in PowerShell from the repository root:

```powershell
Set-Location .\frontend
npm run dev
```

Open `http://localhost:3000`. The frontend needs the backend running at `BACKEND_API_URL` for sign-in, account registration, hospital selection, dataset generation, analytics, validation, health status, and downloads. Browser requests use the frontend origin when the proxy is enabled, preserving the existing credentialed session-cookie flow.

## Production deployment

Set the Vercel project root to `frontend`, configure `BACKEND_API_URL` to the Railway HTTPS API origin, and build with `npm run build`. Do not set `NEXT_PUBLIC_API_BASE_URL` when using the proxy. The Vercel and Railway setup, persistent SQLite volume, backend environment, cookie settings, and verification steps are documented in the [root README](../README.md#production-deployment).

## Available npm scripts

Run these commands from `frontend`:

| Script | Purpose |
| --- | --- |
| `npm run dev` | Start the Next.js development server. |
| `npm run build` | Create an optimized production build and check types. |
| `npm run start` | Serve the production build. |
| `npm run test:role-routing` | Run the role-routing tests with Node's built-in test runner. |

Other checked-in frontend tests can be run directly with Node:

```powershell
node --test src/app/landing-page.test.mjs src/app/settings/settings-page.test.mjs
```

Production output uses `.next-build`; development output uses `.next` so a production build does not replace chunks used by an active development server.
