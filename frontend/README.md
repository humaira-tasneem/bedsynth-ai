# BedSynth AI frontend

Next.js App Router frontend using TypeScript, Tailwind CSS, Lucide icons, Recharts, and Framer Motion. The persistent application shell provides role-based navigation. Administrators use `/admin`, `/hospitals`, `/users`, and `/admin/datasets`; users use `/` and their owned workspace tools. The Synthetic Data Generator at `/generate` provides single-hospital deterministic generation with preview and explicit confirmation. Analytics at `/analytics` is limited to one selected hospital at a time; comparisons require same-hospital runs. The AI Assistant uses Gemini, Groq backup, then explicit local parsing, and never creates records. Statistical utility and privacy-risk evaluations are not part of the current implementation.

## Setup

```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
```

## Run

Start the backend in another terminal, then run:

```powershell
npm run dev
```

Open `http://localhost:3000`. Visit **Hospitals** from the sidebar. If the API has no workspace yet, Hospital Studio creates an empty “My workspace” through the backend; it does not seed hospitals or operational data. Hospital, department, bed, archive, and network operations are persisted through the API.

For a production build: `npm run build`, then `npm run start`. Development artifacts are written to `.next/`; production artifacts are written to `.next-build/` so building production while the development server is open does not replace its chunks.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Browser-visible API base URL. This must not contain credentials or secrets. |

Gemini and Groq API keys are configured only in `backend/.env` as `GEMINI_API_KEY` and `GROQ_API_KEY`. Never add provider keys to this frontend environment or any `NEXT_PUBLIC_*` variable. Assistant conversations are transient in page memory; an approved configuration is handed to `/generate` through browser session storage. Generation still requires a preview and separate confirmation.

Available frontend tests:

```powershell
npm run test:assistant-status
npm run test:role-routing
npm run build
```
