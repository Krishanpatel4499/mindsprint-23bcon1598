const authView = document.querySelector("#auth-view");
const dashboard = document.querySelector("#dashboard");
const authForm = document.querySelector("#auth-form");
const authName = document.querySelector("#auth-name");
const authNameField = document.querySelector("#name-field");
const authError = document.querySelector("#auth-error");
const authSwitch = document.querySelector("#auth-switch");
const taskForm = document.querySelector("#task-form");
const taskList = document.querySelector("#task-list");
const emptyState = document.querySelector("#empty-state");
const planForm = document.querySelector("#plan-form");
const planError = document.querySelector("#plan-error");
const planResult = document.querySelector("#plan-result");
let registrationMode = false;
let toastTimer;

async function api(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...options.headers },
    credentials: "same-origin",
  });
  if (response.status === 204) return null;
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Something went wrong. Please try again.");
  return body;
}

function showAuthError(message = "") {
  authError.textContent = message;
}

function setRegistrationMode(enabled) {
  registrationMode = enabled;
  authNameField.classList.toggle("hidden", !enabled);
  authName.required = enabled;
  document.querySelector("#auth-password").setAttribute(
    "autocomplete",
    enabled ? "new-password" : "current-password",
  );
  document.querySelector("#auth-eyebrow").textContent = enabled ? "A FRESH START, RIGHT THIS WAY" : "YOUR STUDY SPACE";
  document.querySelector("#auth-title").textContent = enabled ? "Let’s get started" : "Welcome back";
  document.querySelector("#auth-subtitle").textContent = enabled
    ? "Your next study win is closer than you think."
    : "A good session starts right here.";
  document.querySelector("#auth-submit").innerHTML = enabled
    ? 'Create my account <span aria-hidden="true">↗</span>'
    : 'Sign in <span aria-hidden="true">↗</span>';
  document.querySelector("#auth-switch-copy").textContent = enabled
    ? "Already have an account?"
    : "New to MindSprint?";
  authSwitch.textContent = enabled ? "Sign in" : "Create an account";
  showAuthError();
}

function showToast(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 2800);
}

function formatDueDate(value) {
  if (!value) return "";
  const due = new Date(`${value}T00:00:00`);
  return `Due ${due.toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

function renderTask(task) {
  const item = document.createElement("article");
  item.className = `task-item${task.completed ? " is-complete" : ""}`;
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.className = "task-check";
  checkbox.checked = task.completed;
  checkbox.setAttribute("aria-label", `Mark ${task.title} as ${task.completed ? "incomplete" : "complete"}`);
  checkbox.addEventListener("change", async () => {
    checkbox.disabled = true;
    try {
      await api(`/api/tasks/${task.id}`, {
        method: "PATCH",
        body: JSON.stringify({ completed: checkbox.checked }),
      });
      await loadTasks();
    } catch (error) {
      checkbox.checked = task.completed;
      checkbox.disabled = false;
      showToast(error.message);
    }
  });

  const copy = document.createElement("div");
  copy.className = "task-copy";
  const title = document.createElement("h3");
  title.textContent = task.title;
  copy.append(title);
  if (task.description) {
    const description = document.createElement("p");
    description.textContent = task.description;
    copy.append(description);
  }
  if (task.due_date) {
    const due = document.createElement("p");
    due.className = "task-date";
    due.textContent = formatDueDate(task.due_date);
    copy.append(due);
  }
  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "delete-task";
  remove.textContent = "×";
  remove.setAttribute("aria-label", `Delete ${task.title}`);
  remove.addEventListener("click", async () => {
    remove.disabled = true;
    try {
      await api(`/api/tasks/${task.id}`, { method: "DELETE" });
      await loadTasks();
      showToast("Study task removed.");
    } catch (error) {
      remove.disabled = false;
      showToast(error.message);
    }
  });
  item.append(checkbox, copy, remove);
  return item;
}

async function loadTasks() {
  const { tasks } = await api("/api/tasks");
  taskList.replaceChildren(...tasks.map(renderTask));
  emptyState.classList.toggle("hidden", tasks.length > 0);
  const completed = tasks.filter((task) => task.completed).length;
  document.querySelector("#completed-count").textContent = completed;
  document.querySelector("#pending-count").textContent = tasks.length - completed;
}

function showDashboard(user) {
  authView.classList.add("hidden");
  dashboard.classList.remove("hidden");
  const name = user.name.trim().split(/\s+/)[0];
  document.querySelector("#greeting").textContent = `You’ve got this, ${name}.`;
  document.querySelector("#today-label").textContent = new Date()
    .toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" })
    .toUpperCase();
  loadTasks().catch((error) => showToast(error.message));
}

authSwitch.addEventListener("click", () => setRegistrationMode(!registrationMode));

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  showAuthError();
  const submit = document.querySelector("#auth-submit");
  submit.disabled = true;
  const form = new FormData(authForm);
  const payload = {
    email: form.get("email"),
    password: form.get("password"),
  };
  if (registrationMode) payload.name = form.get("name");
  try {
    const { user } = await api(registrationMode ? "/api/auth/register" : "/api/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    authForm.reset();
    showDashboard(user);
  } catch (error) {
    showAuthError(error.message);
  } finally {
    submit.disabled = false;
  }
});

document.querySelector("#logout").addEventListener("click", async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
    dashboard.classList.add("hidden");
    authView.classList.remove("hidden");
    setRegistrationMode(false);
    showToast("You’ve signed out. See you soon!");
  } catch (error) {
    showToast(error.message);
  }
});

document.querySelector("#show-task-form").addEventListener("click", () => {
  taskForm.classList.remove("hidden");
  document.querySelector("#task-title").focus();
});

document.querySelector("#cancel-task").addEventListener("click", () => {
  taskForm.reset();
  taskForm.classList.add("hidden");
});

taskForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = taskForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  const form = new FormData(taskForm);
  const dueDate = form.get("due_date");
  try {
    await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        title: form.get("title"),
        description: form.get("description"),
        due_date: dueDate || null,
      }),
    });
    taskForm.reset();
    taskForm.classList.add("hidden");
    await loadTasks();
    showToast("A small step, checked off your list.");
  } catch (error) {
    showToast(error.message);
  } finally {
    submit.disabled = false;
  }
});

planForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  planError.textContent = "";
  planResult.classList.add("hidden");
  const submit = document.querySelector("#plan-submit");
  submit.disabled = true;
  submit.innerHTML = 'Making your plan <span aria-hidden="true">…</span>';
  const form = new FormData(planForm);
  try {
    const result = await api("/api/ai/plan", {
      method: "POST",
      body: JSON.stringify({ goal: form.get("goal"), days: Number(form.get("days")) }),
    });
    const formattedTasks = result.tasks.map((task) => `• ${task.title} — ${formatDueDate(task.due_date)}`).join("\n");
    planResult.textContent = `${result.summary}\n\n${formattedTasks}`;
    planResult.classList.remove("hidden");
    await loadTasks();
    showToast(`${result.tasks.length} study steps added to your checklist.`);
  } catch (error) {
    planError.textContent = error.message;
  } finally {
    submit.disabled = false;
    submit.innerHTML = 'Build my plan <span aria-hidden="true">↗</span>';
  }
});

async function restoreSession() {
  try {
    const { user } = await api("/api/auth/me");
    showDashboard(user);
  } catch {
    authView.classList.remove("hidden");
    dashboard.classList.add("hidden");
  }
}

restoreSession();
