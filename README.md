# Wonky Studio

Asset management tooling for the gamedev team.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Run the Playwright e2e tests:

```bash
cd frontend
npm run test:e2e
```

## Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

The API stores development data in `backend/data/wonky-studio.sqlite3` by default.
Set `WONKY_STUDIO_DB_PATH` to use a different SQLite database file.

Optional auth configuration:

```bash
export WONKY_STUDIO_ORGANIZATION_ID=wonky-studio
export WONKY_STUDIO_FRONTEND_URL=http://127.0.0.1:5173
export WONKY_STUDIO_API_BASE_URL=http://127.0.0.1:8000
export WONKY_STUDIO_SESSION_SECRET=replace-this-in-shared-environments
export WONKY_STUDIO_GOOGLE_CLIENT_ID=your-google-client-id
export WONKY_STUDIO_GOOGLE_CLIENT_SECRET=your-google-client-secret
export WONKY_STUDIO_GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/api/auth/google/callback
```

Create or promote yourself as the first admin:

```bash
cd backend
source .venv/bin/activate
python -m scripts.create_admin you@example.com --name "Your Name"
```

Run the backend e2e tests:

```bash
cd backend
source .venv/bin/activate
pytest
```
