# MindSprint — AI Study Planner

A responsive study planner with secure account registration, a private task checklist, SQLite persistence, and AI-generated study plans.

The page header displays **Krishan Kumar** and registration number **23BCON1598**.

## Run locally

1. Use Python 3.10 or later.
2. Create and activate a virtual environment, then install dependencies:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```

3. Configure the AI key in the current PowerShell session to enable study-plan generation:

   ```powershell
   $env:OPENAI_API_KEY = "your-key"
   ```

   AI planning returns a clear setup error until a key is configured; authentication and task management work without it.

4. Start the server:

   ```powershell
   uvicorn server:app --reload
   ```

5. Open <http://127.0.0.1:8000>.

The local database is created as `studyplanner.db`. Set `DATABASE_PATH` to choose another location. Set `OPENAI_MODEL` to override the default `gpt-4o-mini` model.

## Tests

```powershell
pip install -r requirements-dev.txt
pytest -q
```

## Deploy to Render

The included `render.yaml` configures a free Render web service, health check, generated session-signing secret, and SQLite. It expects this project to be pushed to a GitHub repository connected to Render.

1. Push the project to a GitHub repository.
2. In Render, create a **Blueprint** from that repository and apply `render.yaml`.
3. If prompted, configure `OPENAI_API_KEY` as a secret in the service's **Environment** settings. The blueprint intentionally does not store the API key in source control.
4. Deploy and open the Render-provided URL. `/api/health` is the configured health check.

The free service stores SQLite data on temporary storage, so accounts and tasks may reset when Render restarts or redeploys the app. Free services can also sleep while idle. For persistent data and a production deployment, use a managed database and persistent storage.

## API overview

- `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- `GET /api/tasks`, `POST /api/tasks`, `PATCH /api/tasks/{task_id}`, `DELETE /api/tasks/{task_id}`
- `POST /api/ai/plan`
- `GET /api/health`

Passwords are stored as PBKDF2-HMAC-SHA256 hashes. Signed session cookies are HTTP-only and same-site; cookies use the `Secure` attribute in production. Task reads and changes are scoped to the signed-in user.
