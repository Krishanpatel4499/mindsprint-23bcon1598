import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import urllib.error
import urllib.request
from contextlib import contextmanager, asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = os.environ.get("DATABASE_PATH", str(ROOT / "studyplanner.db"))
SESSION_COOKIE = "study_session"
SESSION_DURATION = timedelta(days=7)
PASSWORD_ITERATIONS = 600_000
APP_SECRET = os.environ.get("APP_SECRET")

if os.environ.get("ENVIRONMENT") == "production" and not APP_SECRET:
    raise RuntimeError("APP_SECRET must be configured in production.")

if not APP_SECRET:
    APP_SECRET = "local-development-only-change-me"


@contextmanager
def database():
    connection = sqlite3.connect(DATABASE_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database():
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    with database() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                due_date TEXT,
                completed INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS tasks_user_id_idx ON tasks(user_id);
            """
        )


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(title="MindSprint Study Planner", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class RegisterRequest(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=8, max_length=128)


class TaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=140)
    description: str = Field(default="", max_length=1000)
    due_date: date | None = None


class TaskUpdateRequest(BaseModel):
    completed: bool


class PlanRequest(BaseModel):
    goal: str = Field(min_length=5, max_length=500)
    days: int = Field(ge=1, le=30)


def password_digest(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"{base64.urlsafe_b64encode(salt).decode()}:{base64.urlsafe_b64encode(digest).decode()}"


def password_matches(password: str, saved_digest: str) -> bool:
    try:
        salt_text, expected_text = saved_digest.split(":", 1)
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(expected_text)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return hmac.compare_digest(actual, expected)


def encode_segment(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def create_session_token(user_id: int) -> str:
    expires = int((datetime.now(timezone.utc) + SESSION_DURATION).timestamp())
    payload = encode_segment(json.dumps({"sub": user_id, "exp": expires}).encode("utf-8"))
    signature = encode_segment(hmac.new(APP_SECRET.encode(), payload.encode(), hashlib.sha256).digest())
    return f"{payload}.{signature}"


def decode_session_token(token: str) -> int | None:
    try:
        payload, signature = token.split(".", 1)
        expected_signature = encode_segment(
            hmac.new(APP_SECRET.encode(), payload.encode(), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected_signature):
            return None
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        claims = json.loads(decoded)
        if int(claims["exp"]) <= int(datetime.now(timezone.utc).timestamp()):
            return None
        return int(claims["sub"])
    except (ValueError, TypeError, KeyError, UnicodeDecodeError, json.JSONDecodeError):
        return None


def set_session_cookie(response: Response, user_id: int):
    response.set_cookie(
        SESSION_COOKIE,
        create_session_token(user_id),
        max_age=int(SESSION_DURATION.total_seconds()),
        httponly=True,
        secure=os.environ.get("ENVIRONMENT") == "production",
        samesite="strict",
        path="/",
    )


def user_response(user: sqlite3.Row) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


def get_current_user(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = decode_session_token(token) if token else None
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in.")
    with database() as connection:
        user = connection.execute(
            "SELECT id, name, email FROM users WHERE id = ?", (user_id,)
        ).fetchone()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Please sign in again.")
    return user_response(user)


CurrentUser = Annotated[dict, Depends(get_current_user)]


def clean_task(task: sqlite3.Row) -> dict:
    return {
        "id": task["id"],
        "title": task["title"],
        "description": task["description"],
        "due_date": task["due_date"],
        "completed": bool(task["completed"]),
    }


def store_task(user_id: int, title: str, description: str, due_date: str | None) -> dict:
    with database() as connection:
        cursor = connection.execute(
            """INSERT INTO tasks (user_id, title, description, due_date, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, title, description, due_date, datetime.now(timezone.utc).isoformat()),
        )
        task = connection.execute(
            "SELECT * FROM tasks WHERE id = ?", (cursor.lastrowid,)
        ).fetchone()
    return clean_task(task)


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, response: Response):
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Enter your name.")
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise HTTPException(status_code=422, detail="Enter a valid email address.")
    try:
        with database() as connection:
            cursor = connection.execute(
                "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
                (
                    name,
                    email,
                    password_digest(payload.password),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            user_id = cursor.lastrowid
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="An account with that email already exists.") from exc
    set_session_cookie(response, user_id)
    return {"user": {"id": user_id, "name": name, "email": email}}


@app.post("/api/auth/login")
def login(payload: LoginRequest, response: Response):
    email = payload.email.strip().lower()
    with database() as connection:
        user = connection.execute(
            "SELECT id, name, email, password_hash FROM users WHERE email = ?", (email,)
        ).fetchone()
    if user is None or not password_matches(payload.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Email or password is incorrect.")
    set_session_cookie(response, user["id"])
    return {"user": user_response(user)}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(SESSION_COOKIE, path="/", httponly=True, samesite="strict")
    return {"status": "ok"}


@app.get("/api/auth/me")
def me(user: CurrentUser):
    return {"user": user}


@app.get("/api/tasks")
def list_tasks(user: CurrentUser):
    with database() as connection:
        tasks = connection.execute(
            "SELECT * FROM tasks WHERE user_id = ? ORDER BY completed ASC, due_date ASC, id DESC",
            (user["id"],),
        ).fetchall()
    return {"tasks": [clean_task(task) for task in tasks]}


@app.post("/api/tasks", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskRequest, user: CurrentUser):
    title = payload.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Task title cannot be blank.")
    task = store_task(
        user["id"],
        title,
        payload.description.strip(),
        payload.due_date.isoformat() if payload.due_date else None,
    )
    return {"task": task}


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdateRequest, user: CurrentUser):
    with database() as connection:
        cursor = connection.execute(
            "UPDATE tasks SET completed = ? WHERE id = ? AND user_id = ?",
            (int(payload.completed), task_id, user["id"]),
        )
        if cursor.rowcount == 0:
            raise HTTPException(status_code=404, detail="Study task not found.")
        task = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return {"task": clean_task(task)}


@app.delete("/api/tasks/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: int, user: CurrentUser):
    with database() as connection:
        cursor = connection.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user["id"])
        )
    if cursor.rowcount == 0:
        raise HTTPException(status_code=404, detail="Study task not found.")


def request_ai_plan(goal: str, days: int) -> dict:
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="AI planning is not configured yet. Add OPENAI_API_KEY to the server environment.",
        )
    today = date.today()
    request_body = {
        "model": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a practical study coach. Return only JSON with a summary string and a tasks "
                    "array. Each task must have title, description, and due_date in YYYY-MM-DD format. "
                    "Create 1 to 7 clear, achievable study tasks, with dates between today and the plan "
                    "deadline. Keep the summary encouraging and concise."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Create a {days}-day study plan starting {today.isoformat()} for this goal: {goal}. "
                    f"The final day is {(today + timedelta(days=days - 1)).isoformat()}."
                ),
            },
        ],
        "temperature": 0.6,
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(request_body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as result:
            provider_response = json.loads(result.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"OpenAI could not generate a plan (HTTP {exc.code})."
        ) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise HTTPException(status_code=502, detail="Could not reach the OpenAI API.") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(status_code=502, detail="OpenAI returned an invalid response.") from exc

    try:
        content = provider_response["choices"][0]["message"]["content"]
        plan = json.loads(content)
        summary = plan["summary"]
        tasks = plan["tasks"]
        if not isinstance(summary, str) or not isinstance(tasks, list) or not 1 <= len(tasks) <= 7:
            raise ValueError("Unexpected plan structure.")
        deadline = today + timedelta(days=days - 1)
        normalized_tasks = []
        for task in tasks:
            title = task["title"].strip()
            description = task.get("description", "").strip()
            due = date.fromisoformat(task["due_date"])
            if (
                not title
                or len(title) > 140
                or len(description) > 1000
                or due < today
                or due > deadline
            ):
                raise ValueError("Unexpected task data.")
            normalized_tasks.append(
                {"title": title, "description": description, "due_date": due.isoformat()}
            )
        return {"summary": summary[:1000], "tasks": normalized_tasks}
    except (KeyError, TypeError, ValueError, IndexError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=502, detail="OpenAI returned a plan in an invalid format.") from exc


@app.post("/api/ai/plan")
def generate_plan(payload: PlanRequest, user: CurrentUser):
    goal = payload.goal.strip()
    if len(goal) < 5:
        raise HTTPException(status_code=422, detail="Describe a study goal using at least five characters.")
    plan = request_ai_plan(goal, payload.days)
    saved_tasks = [
        store_task(user["id"], task["title"], task["description"], task["due_date"])
        for task in plan["tasks"]
    ]
    return {"summary": plan["summary"], "tasks": saved_tasks}
