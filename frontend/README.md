# BedSynth AI frontend

Next.js App Router frontend using TypeScript, Tailwind CSS, Lucide icons, and Recharts. Hospital Studio at `/hospitals` provides backend-connected workspace, network, hospital, department, and bed configuration. Dataset generation and analytics are not implemented.

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
