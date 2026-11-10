const root = "/api/v1/";
const modal = document.querySelector("#modal");
const modalContent = document.querySelector("#modal-content");
const detail = document.querySelector("#detail");
const filters = document.querySelector("#filters");
const notice = document.querySelector("#notice");
let selected = null;
let selectedCycle = null;
let renderToken = 0;

const escape = value => String(value ?? "").replace(/[&<>"']/g, char => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[char]));
const label = value => String(value).replaceAll("_", " ");
const projectPath = id => `projects/${id}/`;
const valueDate = zone => {
  const parts = new Intl.DateTimeFormat("en", {timeZone: zone, year: "numeric",
    month: "2-digit", day: "2-digit"}).formatToParts(new Date());
  const values = Object.fromEntries(parts.map(({type, value}) => [type, value]));
  return `${values.year}-${values.month}-${values.day}`;
};
function errors(data, path = "") {
  if (typeof data === "string") return [path ? `${label(path)}: ${data}` : data];
  if (Array.isArray(data)) return data.flatMap(item => errors(item, path));
  return Object.entries(data ?? {}).flatMap(([key, value]) =>
    errors(value, key === "detail" || key === "non_field_errors" ? path : path ? `${path} / ${key}` : key));
}
async function api(path, method = "GET", data) {
  const csrf = document.querySelector("[name=csrfmiddlewaretoken]").value;
  const response = await fetch(root + path, {method, headers: {
    Accept: "application/json", "Content-Type": "application/json", "X-CSRFToken": csrf,
  }, body: data === undefined ? undefined : JSON.stringify(data)});
  if (response.status === 204) return;
  if (!response.headers.get("content-type")?.includes("json")) {
    throw new Error("The server did not return data. Try reloading or signing in again.");
  }
  const body = await response.json();
  if (!response.ok) throw new Error(errors(body).join(" · "));
  return body;
}
function message(text, error = false) {
  notice.hidden = !text;
  notice.textContent = text;
  notice.classList.toggle("error", error);
}
function safe(action) {
  return (...args) => Promise.resolve().then(() => action(...args))
    .catch(error => message(error.message, true));
}
const option = (value, text, selectedValue) =>
  `<option value="${escape(value)}"${String(value) === String(selectedValue) ? " selected" : ""}>${escape(text)}</option>`;
const input = (title, name, value = "", type = "text", extra = "") =>
  `<label>${escape(title)}<input type="${type}" name="${escape(name)}" value="${escape(value)}" ${extra}></label>`;
const select = (title, name, choices, value = "") =>
  `<label>${escape(title)}<select name="${escape(name)}">${choices.map(([key, text]) => option(key, text, value)).join("")}</select></label>`;
const units = [["days", "Days"], ["weeks", "Weeks"], ["months", "Months"]];
const priorities = [["low", "Low"], ["normal", "Normal"], ["high", "High"]];
const taskStatuses = [["", "All"], ["open", "Open"], ["completed", "Completed"],
  ["partial", "Partial"], ["discarded", "Discarded"]];
const number = (title, name, value) => input(title, name, value, "number", 'step="any"');
const button = (text, action, style = "", data = "") =>
  `<button type="button" class="${style}" data-action="${action}" ${data}>${escape(text)}</button>`;
const toData = form => Object.fromEntries(new FormData(form));
const sparse = data => Object.fromEntries(Object.entries(data).filter(([, value]) => value !== ""));
function modalForm(title, body, onSave, save = "Save", submitStyle = "primary") {
  modalContent.innerHTML = `<header class="modal-heading"><h2 id="modal-title">${escape(title)}</h2>
    <button type="button" data-dismiss aria-label="Close">×</button></header>
    <form novalidate><p class="form-error" role="alert" hidden></p>${body}
    <footer class="actions"><button type="button" data-dismiss${submitStyle === "danger" ? " autofocus" : ""}>Cancel</button>
    <button class="${submitStyle}" type="submit" data-testid="save-form">${escape(save)}</button></footer></form>`;
  const form = modalContent.querySelector("form");
  const error = form.querySelector(".form-error");
  modalContent.querySelectorAll("[data-dismiss]").forEach(item => item.onclick = () => modal.close());
  form.onsubmit = async event => {
    event.preventDefault();
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    error.hidden = true;
    try {
      if (await onSave(toData(form), form) !== false) modal.close();
    } catch (failure) {
      error.textContent = failure.message;
      error.hidden = false;
    } finally {
      submit.disabled = false;
    }
  };
  if (!modal.open) modal.showModal();
  return form;
}
async function reload() {
  const token = ++renderToken;
  const rows = await api("projects/?" + new URLSearchParams(toData(filters)));
  if (token !== renderToken) return;
  const list = document.querySelector("#projects");
  list.innerHTML = rows.length ? rows.map(row => `<button type="button" class="project-link ${row.id === selected ? "selected" : ""}"
      data-project="${row.id}" data-testid="project-link">
      <span>${escape(row.name)}</span><small>${row.review_due ? "Review due" : escape(label(row.status))}</small></button>`).join("")
    : '<p class="muted">No projects match these filters.</p>';
  list.querySelectorAll("[data-project]").forEach(item => item.onclick = safe(async () => {
    selected = Number(item.dataset.project);
    selectedCycle = null;
    await reload();
  }));
  if (!rows.some(row => row.id === selected)) {
    selected = rows[0]?.id ?? null;
    selectedCycle = null;
    list.querySelector(`[data-project="${selected}"]`)?.classList.add("selected");
  }
  if (selected === null) {
    detail.innerHTML = '<article class="card empty"><h2>Choose a project</h2><p>Create a project to plan and track your first outcome.</p></article>';
    return;
  }
  const path = projectPath(selected);
  const project = await api(path);
  if (token !== renderToken) return;
  const chosen = project.cycles.find(row => row.id === selectedCycle) ??
    project.cycles.find(row => !row.closed_at && !row.is_draft) ??
    project.cycles.find(row => !row.is_draft);
  const results = await Promise.all([
    chosen ? api(`${path}cycles/${chosen.id}/`) : null,
    project.mode === "standard" ? null : api(path + "ledger/"),
    project.status === "closed" ? api(path + "report/") : null,
  ]);
  if (token !== renderToken) return;
  renderProject(project, ...results);
}
function goalValue(value, kind, currency) {
  return kind === "net_income" ? `${Number(value).toLocaleString("en")} ${escape(currency)}` : value;
}
function goalCard(goal, canChange, project, cycle) {
  const progress = goal.quantity ? Math.min(100, Math.round(goal.actual * 100 / goal.quantity)) : 100;
  const counter = goal.kind === "done" ? (goal.actual || goal.previous_actual ? "Done" : "Pending")
    : `${goalValue(goal.actual, goal.kind, project.currency)} / ${goalValue(goal.quantity, goal.kind, project.currency)}${goal.kind === "hours" ? " h" : ""}`;
  const ledgerNote = {
    hours: "Updates from linked work in the income ledger.",
    net_income: "Updates from after-tax income earned in this cycle.",
  }[goal.kind];
  return `<div class="goal"><div class="line"><strong>${escape(goal.name)}</strong><span class="count">${counter}</span></div>
    <progress max="100" value="${progress}" aria-label="${escape(goal.name)}"></progress>
    <small>${goalValue(goal.cumulative, goal.kind, project.currency)} cumulative ·
      ${goalValue(goal.remaining_original, goal.kind, project.currency)} remaining against original target</small>
    <div class="actions">${ledgerNote ? `<small>${ledgerNote}</small>`
      : cycle.is_draft || cycle.status === "scheduled" ? ""
      : button("Daily entry", "entry", "", `data-target="${goal.id}" data-testid="daily-entry"`)}
    ${canChange && !cycle.is_draft && project.mode === "hourly" && goal.kind === "count" && !goal.actual && !goal.previous_actual
      ? button("Switch to hours", "goal-hours", "", `data-target="${goal.id}"`) : ""}
    ${canChange ? button("Delete goal", "delete-goal", "danger-outline", `data-target="${goal.id}"`) : ""}</div></div>`;
}
function renderProject(project, cycle, ledger, report) {
  const path = projectPath(project.id);
  const isOpen = project.status === "active";
  const reportSection = report ? `<article class="card"><div class="line"><h2>Final report</h2><div class="actions">
    <a class="button" href="${root + path}report.pdf">Download PDF</a><a class="button" href="${root + path}report.xlsx">Download Excel</a>
    </div></div>${table(["Task", "Goal", "Planned", "Actual", "Gap", "Reason"],
      report.goals.map(row => [row.task, row.goal, row.planned, row.actual, row.gap, row.reason]))}</article>` : "";
  const currentCycle = project.cycles.find(row => !row.closed_at && !row.is_draft);
  const cycleList = `<article class="card"><div class="line"><h2>Project cycles</h2>
    ${isOpen ? button("Plan next cycle", "draft-cycle", "primary") : ""}</div>
    <ul class="ledger-list">${project.cycles.map(item => `<li class="line">
      ${button(`Cycle ${item.sequence} · ${item.start} to ${item.end}`, "view-cycle",
        item.id === cycle?.id ? "primary" : "", `data-cycle="${item.id}"`)}
      <span class="pill">${escape(label(item.status))}</span></li>`).join("")}</ul></article>`;
  const cycleSection = cycle ? `<article class="card"><div class="line"><h2>Cycle ${cycle.sequence}</h2><span class="pill">${escape(label(cycle.status))}</span></div>
    <div class="cycle-toolbar"><p>${cycle.start} to ${cycle.end}</p>
    ${select("Filter tasks", "local-status", taskStatuses)}</div>
    ${cycle.is_draft ? '<p class="muted">You can plan this cycle now. Progress opens after the previous cycle closes and the start date arrives.</p>' : ""}
    <div class="actions">${isOpen && !cycle.closed_at
      ? button("Edit cycle dates", "edit-cycle") + button("Add task", "task", "primary", 'data-testid="add-task"') : ""}
    ${cycle.status === "review" && isOpen ? button("Review and close cycle", "review", "primary", 'data-testid="review-cycle"') : ""}</div>
    <div id="plans">${cycle.plans.map(plan => `<section class="task" data-status="${escape(plan.status)}">
      <div class="line"><div><h3>${escape(plan.name)}</h3><small>${plan.kind ? `${escape(plan.kind)} · ` : ""}${escape(plan.priority)} priority</small></div>
      <span class="pill">${escape(plan.decision || plan.status)}</span></div>
      ${plan.reason ? `<p class="muted">${escape(plan.reason)} ${escape(plan.note)}</p>` : ""}
      ${plan.description ? `<p>${escape(plan.description)}</p>` : ""}
      ${plan.reference_url ? `<p class="muted">Reference · ${escape(plan.reference_url)}</p>` : ""}
      ${Object.keys(plan.values).length ? `<dl class="values">${Object.entries(plan.values).map(([key, value]) =>
        `<div><dt>${escape(label(key))}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>` : ""}
      ${plan.targets.map(goal => goalCard(goal, !cycle.closed_at && isOpen && plan.status === "open", project, cycle)).join("")}
      <div class="actions">
      ${!cycle.closed_at && isOpen && plan.status === "open"
        ? button("Edit plan", "plan", "", `data-plan="${plan.id}"`) +
          button("Add goal", "goal", "", `data-plan="${plan.id}"`) : ""}
      ${!cycle.closed_at && !cycle.is_draft && cycle.status !== "scheduled" && isOpen &&
        plan.status === "open" && plan.targets.every(goal => goal.actual >= goal.quantity)
        ? button("Confirm complete", "complete", "", `data-plan="${plan.id}"`) : ""}
      ${!cycle.closed_at && isOpen
        ? button("Delete task", "delete-task", "danger-outline", `data-plan="${plan.id}"`) : ""}</div></section>`).join("") ||
    '<p class="muted">No tasks planned in this cycle.</p>'}</div></article>` : "";
  detail.innerHTML = `<article class="card project-header"><div class="line"><div><p class="eyebrow">Selected project</p>
    <h2>${escape(project.name)}</h2></div><span class="pill">${escape(label(project.status))}</span></div>
    <dl class="values"><div><dt>Started</dt><dd>${project.start}</dd></div>
    <div><dt>Planned end</dt><dd>${project.planned_end || "—"}</dd></div>
    <div><dt>Review interval</dt><dd>${project.interval} ${escape(project.interval_unit)}</dd></div>
    <div><dt>Project type</dt><dd>${escape(label(project.mode))}</dd></div>
    ${project.closed_on ? `<div><dt>Closed</dt><dd>${project.closed_on}</dd></div>` : ""}</dl>
    <div class="actions">${isOpen ? button("Edit project", "edit-project") + button("Task types", "kinds") : ""}
    ${project.status !== "closed" ? button(project.status === "awaiting_payment" ? "Confirm closure" : "End project", "finish") : ""}
    ${button("Delete project", "delete-project", "danger-outline", 'data-testid="delete-project"')}</div>
    </article>${cycleList}${reportSection}${cycleSection}${ledger ? ledgerHtml(project, ledger) : ""}`;
  detail.querySelector("[name=local-status]")?.addEventListener("change", event => {
    detail.querySelectorAll("[data-status]").forEach(item => {
      item.hidden = Boolean(event.target.value && item.dataset.status !== event.target.value);
    });
  });
  const findPlan = element => cycle.plans.find(plan => plan.id === Number(element.dataset.plan));
  const findGoal = element => cycle.plans.flatMap(plan => plan.targets)
    .find(goal => goal.id === Number(element.dataset.target));
  const actions = {
    "edit-project": () => projectForm(project, currentCycle), kinds: () => kindPicker(project),
    "edit-cycle": () => cycleDatesForm(project, cycle),
    "draft-cycle": () => draftCycleForm(project),
    "view-cycle": async element => {
      selectedCycle = Number(element.dataset.cycle);
      await reload();
    },
    "delete-project": () => modalForm("Delete project?", `<p>Permanently delete <strong>${escape(project.name)}</strong>
      and its tasks, progress, and financial records? This action cannot be undone.</p>`, async () => {
      await api(path, "DELETE");
      selected = null;
      selectedCycle = null;
      detail.replaceChildren();
      message(`Deleted project: ${project.name}`);
      await safe(reload)();
    }, "Delete project", "danger"),
    task: () => taskForm(project, cycle), review: () => reviewForm(project, cycle),
    finish: async () => reviewForm(project, currentCycle ? await api(`${path}cycles/${currentCycle.id}/`) : null, true),
    complete: element => modalForm("Confirm task completion", "<p>This closes the task for new daily entries.</p>", async () => {
      await api(path + `plans/${element.dataset.plan}/complete/`, "POST", {});
      await reload();
    }, "Confirm complete"),
    plan: element => planForm(project, findPlan(element)),
    goal: element => goalForm(project, findPlan(element)),
    "delete-task": element => {
      const plan = findPlan(element);
      confirmDelete("task", plan.name, path + `tasks/${plan.task_id}/`,
        "Its goals and recorded progress will also be deleted.");
    },
    "delete-goal": element => {
      const goal = findGoal(element);
      confirmDelete("goal", goal.name, path + `goals/${goal.goal_id}/`,
        ["hours", "net_income"].includes(goal.kind) ? "Recorded work stays in the income ledger." : "Its recorded progress will also be deleted.");
    },
    "goal-hours": element => hoursGoalForm(project, findGoal(element)),
    entry: element => {
      const id = Number(element.dataset.target);
      const plan = cycle.plans.find(row => row.targets.some(target => target.id === id));
      return entryForm(project, cycle, plan, plan.targets.find(target => target.id === id));
    },
    terms: () => termsForm(project), hourly: async () => hourlyForm(project, cycle?.is_draft && currentCycle
      ? await api(`${path}cycles/${currentCycle.id}/`) : cycle),
    monthly: () => monthlyForm(project),
    payment: element => paymentForm(project, ledger.items.find(item => item.id === Number(element.dataset.receivable))),
    "delete-receivable": element => {
      const item = ledger.items.find(row => row.id === Number(element.dataset.receivable));
      confirmDelete("income entry", item.month?.slice(0, 7) || item.work_day, path + `ledger/${item.id}/`,
        "Any goal progress based on this entry will be recalculated.");
    },
    "delete-payment": element => {
      const item = ledger.items.find(row => row.id === Number(element.dataset.receivable));
      const payment = item.payments.find(row => row.id === Number(element.dataset.payment));
      confirmDelete("payment", `${payment.amount} ${project.currency} on ${payment.received_on}`,
        path + `ledger/${item.id}/payments/${payment.id}/`, "The outstanding balance will increase.");
    },
  };
  detail.querySelectorAll("[data-action]").forEach(element => {
    element.onclick = safe(() => actions[element.dataset.action](element));
  });
}
function table(headers, rows) {
  return rows.length ? `<div class="table-wrap"><table><thead><tr>${headers.map(value => `<th scope="col">${escape(value)}</th>`).join("")}
    </tr></thead><tbody>${rows.map(row => `<tr>${row.map(value => `<td>${escape(value)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>`
    : '<p class="muted">No records yet.</p>';
}
function confirmDelete(noun, name, path, impact = "") {
  return modalForm(`Delete ${noun}?`, `<p>Permanently delete <strong>${escape(name)}</strong>? ${escape(impact)}</p>`,
    async () => {
      await api(path, "DELETE");
      message(`Deleted ${noun}: ${name}`);
      await safe(reload)();
    }, `Delete ${noun}`, "danger");
}
function cycleDateFields(cycle) {
  return `<div class="form-grid">
    ${input("Start date", "start", cycle.start, "date", cycle.sequence === 1 ? "" : "disabled")}
    ${input("Review date", "end", cycle.end, "date")}</div>`;
}
function cycleDatesForm(project, cycle) {
  return modalForm(`Edit cycle ${cycle.sequence} dates`, cycleDateFields(cycle), async data => {
    await api(projectPath(project.id) + `cycles/${cycle.id}/`, "PATCH", data);
    await safe(reload)();
  });
}
async function draftCycleForm(project) {
  const path = projectPath(project.id) + "cycles/";
  const previous = await api(path + `${project.cycles[0].id}/`);
  const suggestions = previous.plans.map(plan => `<label class="check">
    <input type="checkbox" name="source_plan_ids" value="${plan.id}">${escape(plan.name)}</label>`).join("");
  modalForm("Plan next cycle", `<p>Create a draft after cycle ${previous.sequence}. Select tasks to copy as new work.</p>
    ${suggestions ? `<fieldset><legend>Suggested tasks from the previous plan</legend>${suggestions}</fieldset>` : ""}
    <p class="muted">If you want to continue an unfinished task, choose Carry forward when reviewing its cycle.</p>`,
  async (_, form) => {
    const source_plan_ids = new FormData(form).getAll("source_plan_ids").map(Number);
    const draft = await api(path, "POST", {source_plan_ids});
    selectedCycle = draft.id;
    await safe(reload)();
  }, "Create draft");
}
async function projectForm(project = null, cycle = null) {
  if (project) {
    return modalForm("Edit project", `<div class="form-grid">
      ${input("Project name", "name", project.name)}
      ${input("Planned end (optional)", "planned_end", project.planned_end, "date")}</div>
      ${cycle ? `<fieldset><legend>Current cycle dates</legend>${cycleDateFields(cycle)}</fieldset>` : ""}`,
    async ({name, planned_end, ...dates}) => {
      await api(projectPath(project.id), "PATCH", {name, planned_end: planned_end || null,
        ...(cycle ? {cycle: dates} : {})});
      await safe(reload)();
    });
  }
  const pref = await api("preferences/");
  const form = modalForm("New project", `<p class="eyebrow" data-step aria-live="polite"></p>
    <section data-project-settings>
      ${input("Project name", "name", "", "text", "required maxlength=160")}
      <div class="form-grid">
        ${select("Project type", "mode", [["standard", "Standard"], ["hourly", "Hourly income"], ["monthly", "Monthly income"]], "standard")}
        ${input("Review interval", "interval", pref.interval, "number", "required min=1 max=365 step=1")}
        ${select("Interval unit", "interval_unit", units, pref.interval_unit)}
      </div>
      <div data-currency hidden>${input("Currency", "currency", pref.currency, "text", 'required pattern="[A-Za-z]{3}"')}</div>
      <details><summary>Dates and review settings</summary><div class="form-grid">
        ${input("Start date", "start", valueDate(pref.timezone), "date", "required")}
        ${input("First review (optional)", "first_review", "", "date")}
        ${input("Planned end (optional)", "planned_end", "", "date")}
      </div></details>
    </section>
    <section data-project-tasks hidden>
      <p class="muted">Add your first tasks now or create the project and add them later.</p>
      <div data-task-list></div>
      <div class="actions">${button("Back", "wizard-back")}${button("Add task", "wizard-add")}</div>
    </section>`, async () => {
      if (step === 1) {
        checkProject();
        showStep(2);
        return false;
      }
      const data = sparse(fieldValues(settings));
      if (data.mode === "standard") delete data.currency;
      data.tasks = editors.map(editor => editor.read());
      const result = await api("projects/", "POST", data);
      selected = result.id;
      selectedCycle = null;
      filters.reset();
      await safe(reload)();
    }, "Next");
  const settings = form.querySelector("[data-project-settings]");
  const tasks = form.querySelector("[data-project-tasks]");
  const mode = settings.querySelector("[name=mode]");
  const currency = settings.querySelector("[data-currency]");
  const editors = [];
  let step;
  function checkProject() {
    const data = fieldValues(settings);
    if (!data.name.trim()) throw new Error("Enter a project name.");
    if (!data.start) throw new Error("Choose a start date.");
    if (!settings.querySelector("[name=interval]").checkValidity()) {
      throw new Error("Enter a review interval between 1 and 365.");
    }
    if ([data.first_review, data.planned_end].some(day => day && day < data.start)) {
      throw new Error("The review and end dates must be on or after the start date.");
    }
    if (mode.value !== "standard" && !currency.querySelector("input").checkValidity()) {
      throw new Error("Enter a three-letter currency code.");
    }
  }
  function showStep(number) {
    step = number;
    settings.hidden = step !== 1;
    tasks.hidden = step !== 2;
    form.querySelector("[data-step]").textContent =
      step === 1 ? "1 of 2 · Project details" : "2 of 2 · Tasks and goals";
    form.querySelector("[type=submit]").textContent = step === 1 ? "Next" : "Create project";
  }
  mode.onchange = () => {
    currency.hidden = mode.value === "standard";
    editors.forEach(editor => editor.setMode(mode.value));
  };
  form.querySelector("[data-action=wizard-back]").onclick = () => {
    form.querySelector(".form-error").hidden = true;
    showStep(1);
    settings.querySelector("[name=name]").focus();
  };
  form.querySelector("[data-action=wizard-add]").onclick = () => {
    if (editors.length >= 50) return;
    const editor = taskEditor({mode: mode.value, kinds: []}, () => {
      editors.splice(editors.indexOf(editor), 1);
      editor.element.remove();
    });
    editors.push(editor);
    tasks.querySelector("[data-task-list]").append(editor.element);
    editor.element.querySelector("[name=task_name]").focus();
  };
  showStep(1);
}
function fieldRows(schema, values = {}) {
  return schema.map(field => {
    const title = field.label + (field.required ? " *" : "");
    if (field.type === "choice") return select(title, field.key, [["", "Choose…"], ...field.choices.map(item => [item, item])], values[field.key]);
    if (field.type === "number") return number(title, field.key, values[field.key]);
    return input(title, field.key, values[field.key], field.type);
  }).join("");
}
function fieldValues(container) {
  return Object.fromEntries(Array.from(container.querySelectorAll("input,select")).map(control => [control.name, control.value]));
}
function kindPicker(project) {
  const form = modalForm("Task types", select("Type", "kind", [["", "Create a new type"],
    ...project.kinds.map(kind => [kind.id, kind.name])]), async () => {}, "Continue");
  form.onsubmit = event => {
    event.preventDefault();
    const id = Number(toData(form).kind);
    kindForm(project, project.kinds.find(kind => kind.id === id));
  };
}
function kindForm(project, kind) {
  const form = modalForm(kind ? "Edit task type" : "New task type", `${input("Type name", "name", kind?.name)}
    ${kind ? button("Delete task type", "delete-kind", "danger-outline") : ""}
    <p class="muted">Changes apply to new tasks. Existing tasks keep their saved fields.</p>
    <fieldset><legend>Task fields</legend><div data-fields="task_fields"></div>${button("Add task field", "add", "", 'data-list="task_fields"')}</fieldset>
    <fieldset><legend>Output detail fields</legend><div data-fields="entry_fields"></div>${button("Add detail field", "add", "", 'data-list="entry_fields"')}</fieldset>`,
    async ({name}) => {
      const body = {name};
      for (const key of ["task_fields", "entry_fields"]) {
        body[key] = Array.from(form.querySelectorAll(`[data-fields="${key}"] .builder-row`)).map(row => {
          const field = fieldValues(row);
          return {key: field.key, label: field.label, type: field.type,
            required: row.querySelector("[name=required]").checked,
            choices: field.type === "choice" ? field.choices.split(",").map(item => item.trim()).filter(Boolean) : []};
        });
      }
      await api(projectPath(project.id) + "kinds/" + (kind ? `${kind.id}/` : ""), kind ? "PATCH" : "POST", body);
      await reload();
    });
  if (kind) form.querySelector("[data-action=delete-kind]").onclick = () =>
    confirmDelete("task type", kind.name, projectPath(project.id) + `kinds/${kind.id}/`);
  function add(key, field = {}) {
    const row = document.createElement("div");
    row.className = "builder-row";
    row.innerHTML = `<div class="form-grid">${input("Field key", "key", field.key)}
      ${input("Label", "label", field.label)}${select("Type", "type",
      ["text", "number", "date", "url", "choice"].map(type => [type, type]), field.type || "text")}
      ${input("Choices (comma-separated)", "choices", field.choices?.join(", "))}
      <label class="check"><input type="checkbox" name="required" ${field.required ? "checked" : ""}>Required</label></div>
      <button type="button" data-remove>Remove field</button>`;
    row.querySelector("[data-remove]").onclick = () => row.remove();
    form.querySelector(`[data-fields="${key}"]`).append(row);
  }
  form.querySelectorAll("[data-list]").forEach(item => item.onclick = () => add(item.dataset.list));
  for (const key of ["task_fields", "entry_fields"]) (kind?.[key] || []).forEach(field => add(key, field));
}
function goalEditor(mode, remove) {
  const row = document.createElement("div");
  row.className = "builder-row";
  row.innerHTML = `<div class="form-grid">${input("Goal name", "name", "", "text", "maxlength=160")}
    ${select("Measurement", "kind", [["done", "Done / not done"], ["count", "Count outputs"],
      ["hours", "Hours worked"], ["net_income", "Net income"]], "done")}
    ${input("Target quantity", "quantity", 1, "number")}</div>
    <details><summary>Reporting label (optional)</summary>
    ${input("Metric", "metric", "", "text", "maxlength=100")}</details>
    ${remove ? button("Remove goal", "remove-goal") : ""}`;
  const kind = row.querySelector("[name=kind]");
  const quantity = row.querySelector("[name=quantity]");
  function updateQuantity() {
    const quantityLabel = quantity.closest("label");
    quantityLabel.hidden = kind.value === "done";
    quantityLabel.firstChild.textContent =
      kind.value === "net_income" ? "Target amount (project currency)" : "Target quantity";
    const decimal = ["hours", "net_income"].includes(kind.value);
    quantity.min = decimal ? "0.01" : "1";
    quantity.step = decimal ? "0.01" : "1";
  }
  function setMode(mode) {
    const hours = kind.querySelector('[value="hours"]');
    const income = kind.querySelector('[value="net_income"]');
    hours.hidden = hours.disabled = mode !== "hourly" && kind.value !== "hours";
    income.hidden = income.disabled = mode === "standard" && kind.value !== "net_income";
  }
  kind.onchange = () => { updateQuantity(); setMode(currentMode); };
  if (remove) row.querySelector("[data-action=remove-goal]").onclick = remove;
  let currentMode = mode;
  updateQuantity();
  setMode(mode);
  return {element: row, setMode(mode) { currentMode = mode; setMode(mode); }, read() {
    const data = sparse(fieldValues(row));
    if (!data.name?.trim()) throw new Error("Enter a name for each goal or remove the empty goal.");
    if (data.kind === "hours" && currentMode !== "hourly") {
      throw new Error("Choose another measurement or change the project type to Hourly income.");
    }
    if (data.kind === "net_income" && currentMode === "standard") {
      throw new Error("Choose another measurement or select an income project type.");
    }
    if (data.kind !== "done" && (!data.quantity || !quantity.checkValidity())) {
      throw new Error("Enter a valid positive target quantity.");
    }
    return {...data, quantity: data.kind === "done" ? 1 : data.quantity};
  }};
}
function taskEditor(project, remove) {
  const editor = document.createElement("fieldset");
  editor.innerHTML = `<legend>Task</legend>
    ${input("Task name", "task_name", "", "text", "maxlength=160")}
    <details><summary>Task information (optional)</summary><div class="form-grid">
      <label>Description<textarea name="description" maxlength="2000" rows="2"></textarea></label>
      ${input("Reference URL", "reference_url", "", "url", "maxlength=2048")}
      ${select("Priority", "priority", priorities, "normal")}
      ${project.kinds.length ? select("Task type (optional)", "kind_id",
        [["", "No type"], ...project.kinds.map(kind => [kind.id, kind.name])]) : ""}
    </div><div class="form-grid" data-values></div></details>
    <div data-goals></div>
    <div class="actions">${button("Add goal", "add-goal")}${remove ? button("Remove task", "remove-task") : ""}</div>`;
  const kind = editor.querySelector("[name=kind_id]");
  if (kind) kind.onchange = () => {
    const template = project.kinds.find(item => item.id === Number(kind.value));
    editor.querySelector("[data-values]").innerHTML = fieldRows(template?.task_fields || []);
  };
  const goals = [];
  let mode = project.mode;
  editor.querySelector("[data-action=add-goal]").onclick = () => {
    if (goals.length >= 20) return;
    const goal = goalEditor(mode, () => {
      goals.splice(goals.indexOf(goal), 1);
      goal.element.remove();
    });
    goals.push(goal);
    editor.querySelector("[data-goals]").append(goal.element);
    goal.element.querySelector("[name=name]").focus();
  };
  if (remove) editor.querySelector("[data-action=remove-task]").onclick = remove;
  return {element: editor, setMode(nextMode) {
    mode = nextMode;
    goals.forEach(goal => goal.setMode(mode));
  }, read() {
    const name = editor.querySelector("[name=task_name]").value.trim();
    if (!name) throw new Error("Enter a name for each task or remove the empty task.");
    return {name, priority: editor.querySelector("[name=priority]").value,
      description: editor.querySelector("[name=description]").value,
      reference_url: editor.querySelector("[name=reference_url]").value,
      ...(kind?.value ? {kind_id: kind.value} : {}),
      values: fieldValues(editor.querySelector("[data-values]")), goals: goals.map(goal => goal.read())};
  }};
}
function taskForm(project, cycle) {
  const editor = taskEditor(project);
  const form = modalForm("New task", '<div data-editor></div>', async () => {
    const path = cycle.is_draft ? `cycles/${cycle.id}/tasks/` : "tasks/";
    await api(projectPath(project.id) + path, "POST", editor.read());
    await safe(reload)();
  });
  form.querySelector("[data-editor]").append(editor.element);
  editor.element.querySelector("[name=task_name]").focus();
}
function goalForm(project, plan) {
  const editor = goalEditor(project.mode);
  const form = modalForm("New goal", '<div data-editor></div>', async () => {
    await api(projectPath(project.id) + `plans/${plan.id}/goals/`, "POST", editor.read());
    await safe(reload)();
  });
  form.querySelector("[data-editor]").append(editor.element);
  editor.element.querySelector("[name=name]").focus();
}
function hoursGoalForm(project, goal) {
  modalForm("Switch to Hours worked", `<p>Progress will come from hours already linked to this task in the income ledger.</p>
    ${number("Target hours", "quantity", goal.quantity)}`, async data => {
    await api(projectPath(project.id) + `goals/${goal.goal_id}/`, "PATCH", data);
    await safe(reload)();
  }, "Switch to hours");
}
function planForm(project, plan) {
  const goals = plan.targets.map(target => target.kind === "done"
    ? `<p><strong>${escape(target.name)}</strong> · Done / not done</p>`
    : number(`Target for ${target.name}${target.kind === "net_income" ? ` (${project.currency})` : ""}`,
      `target-${target.id}`, target.quantity)).join("");
  modalForm("Edit cycle plan", `<div class="form-grid">
    ${input("Task name", "name", plan.name, "text", "maxlength=160")}
    ${select("Priority", "priority", priorities, plan.priority)}
    <label>Description<textarea name="description" maxlength="2000" rows="2">${escape(plan.description)}</textarea></label>
    ${input("Reference URL", "reference_url", plan.reference_url, "url", "maxlength=2048")}</div>
    <fieldset><legend>Goals</legend>${goals || '<p class="muted">No goals in this cycle. Use Add goal to create one.</p>'}</fieldset>`,
  async ({name, description, reference_url, priority, ...quantities}) => {
    const targets = Object.fromEntries(Object.entries(quantities).map(([key, value]) => [key.slice(7), value]));
    await api(projectPath(project.id) + `plans/${plan.id}/`, "PATCH",
      {name, description, reference_url, priority, targets});
    await reload();
  });
}
async function entryForm(project, cycle, plan, target) {
  const pref = await api("preferences/");
  const path = projectPath(project.id) + `targets/${target.id}/entries/`;
  const dates = await api(path);
  const today = valueDate(pref.timezone);
  const suggested = dates.at(-1) && cycle.closed_at ? dates.at(-1)
    : today < cycle.start ? cycle.start : today > cycle.end ? cycle.end : today;
  const form = modalForm(target.name, `<div class="form-grid">${input("Entry date", "day", suggested, "date")}
    ${select("Saved dates", "saved", [["", "Choose a date"], ...dates.map(day => [day, day])])}</div>
    <p class="muted" data-entry-status></p><p data-history></p><div data-items></div>
    ${button(target.kind === "done" ? "Mark done" : "Add output", "add-output")}
    ${cycle.closed_at ? input("Reason for correction", "reason") : ""}`, async data => {
      const items = Array.from(form.querySelectorAll(".builder-row")).map(row => fieldValues(row));
      if (loadedDay !== data.day) throw new Error("Load a valid entry date before saving.");
      await api(path + `${encodeURIComponent(data.day)}/`, "PUT", {items, ...(data.reason ? {reason: data.reason} : {})});
      await reload();
    });
  let loadedDay = null;
  const container = form.querySelector("[data-items]");
  const status = form.querySelector("[data-entry-status]");
  const add = form.querySelector("[data-action=add-output]");
  const day = form.querySelector("[name=day]");
  function update() {
    const count = container.children.length;
    status.textContent = `${count} ${count === 1 ? "output" : "outputs"} recorded for this date`;
    add.disabled = target.kind === "done" && count > 0;
  }
  function addItem(values = {}) {
    const row = document.createElement("div");
    row.className = "builder-row";
    row.innerHTML = `<div class="form-grid">${fieldRows(plan.entry_fields, values)}</div>
      <button type="button" data-remove>Remove output</button>`;
    row.querySelector("[data-remove]").onclick = () => { row.remove(); update(); };
    container.append(row);
    update();
  }
  async function load() {
    const date = day.value;
    loadedDay = null;
    status.textContent = "Loading…";
    try {
      const entry = await api(path + `${encodeURIComponent(date)}/`);
      if (date !== day.value) return;
      container.replaceChildren();
      entry.items.forEach(addItem);
      form.querySelector("[data-history]").textContent = entry.corrections.map(change => change.reason).join(" · ");
      loadedDay = date;
      update();
    } catch (error) {
      if (date === day.value) status.textContent = error.message;
    }
  }
  add.onclick = () => addItem();
  day.onchange = load;
  form.querySelector("[name=saved]").onchange = event => {
    if (event.target.value) { day.value = event.target.value; load(); }
  };
  await load();
}
async function reviewForm(project, cycle, finish = false) {
  const reasons = (await api("reasons/")).filter(item => item.active);
  const plans = cycle?.plans.filter(plan => plan.status === "open") || [];
  const choices = [["", "Choose a decision"], ["complete", "Confirm complete"],
    ...(!finish ? [["carry", "Carry forward"]] : []), ["partial", "Close with partial progress"], ["discard", "Discard"]];
  const body = plans.map(plan => `<fieldset><legend>${escape(plan.name)}</legend>
    <p>${plan.targets.map(goal => `${escape(goal.name)}: ${goal.actual}/${goal.quantity}`).join(" · ")}</p>
    <div class="form-grid">${select("Decision", `action-${plan.id}`, choices)}
    ${select("Reason", `reason-${plan.id}`, [["", "Choose a reason"], ...reasons.map(item => [item.id, item.label])])}
    ${input("Note (optional)", `note-${plan.id}`)}</div></fieldset>`).join("");
  modalForm(finish ? "End project" : `Review cycle ${cycle.sequence}`, body || "<p>No open tasks to review. Confirm to continue.</p>",
    async data => {
      const decisions = Object.fromEntries(plans.map(plan => [plan.id, {action: data[`action-${plan.id}`],
        ...(data[`reason-${plan.id}`] ? {reason_id: data[`reason-${plan.id}`]} : {}), note: data[`note-${plan.id}`]}]));
      await api(projectPath(project.id) + (finish ? "finish/" : `cycles/${cycle.id}/review/`), "POST", {decisions});
      selectedCycle = null;
      await reload();
    }, finish ? "Confirm project closure" : "Close cycle");
}
function ledgerHtml(project, ledger) {
  const active = project.status === "active";
  const rows = ledger.items.map(item => `<li class="task"><div class="line">
    <strong>${escape(item.month?.slice(0, 7) || item.work_day)}</strong><span class="pill">${escape(item.status)}</span></div>
    <dl class="values"><div><dt>Gross</dt><dd>${escape(item.gross)}</dd></div>
    <div><dt>Tax</dt><dd>${escape(item.tax)}</dd></div><div><dt>Net</dt><dd>${escape(item.net)}</dd></div>
    <div><dt>Received</dt><dd>${escape(item.received)}</dd></div><div><dt>Remaining</dt><dd>${escape(item.remaining)}</dd></div>
    ${item.hours ? `<div><dt>Hours</dt><dd>${escape(item.hours)}</dd></div>` : ""}
    ${item.location ? `<div><dt>Location</dt><dd>${escape(item.location)}</dd></div>` : ""}</dl>
    ${item.payments.length ? `<ul class="ledger-list" aria-label="Payments">${item.payments.map(payment => `<li class="line">
      <span>${escape(payment.received_on)} · ${escape(payment.amount)} ${escape(ledger.currency)}</span>
      ${project.status !== "closed" ? button("Delete payment", "delete-payment", "danger-outline",
        `data-receivable="${item.id}" data-payment="${payment.id}"`) : ""}</li>`).join("")}</ul>` : ""}
    <div class="actions">
    ${project.status !== "closed" && Number(item.remaining) > 0 ? button("Record payment", "payment", "", `data-receivable="${item.id}"`) : ""}
    ${active && !item.payments.length ? button("Delete income entry", "delete-receivable", "danger-outline", `data-receivable="${item.id}"`) : ""}
    </div></li>`).join("");
  return `<article class="card"><div class="line"><h2>Income ledger · ${escape(ledger.currency)}</h2><span class="pill">${escape(ledger.remaining)} remaining</span></div>
    <div class="actions">${active ? button("Pay terms", "terms") + (project.mode === "hourly"
      ? button("Record hourly work", "hourly", "primary") : button("Record partial month", "monthly", "primary")) : ""}</div>
    <h3>Received by month</h3>${table(["Month", "Received"], Object.entries(ledger.received_by_month).sort().reverse())}
    <h3>Receivables</h3>${rows ? `<ul class="ledger-list">${rows}</ul>` : '<p class="muted">No receivables yet.</p>'}</article>`;
}
async function termsForm(project) {
  const path = projectPath(project.id) + "terms/";
  const rows = await api(path);
  const form = modalForm("Pay terms", rows.map(row => `<div class="line builder-row">
    <span>Effective ${escape(row.effective_on)} · ${escape(row.rate)} ${escape(project.currency)} · ${escape(row.tax_pct)}% tax</span>
    ${button("Delete pay terms", "delete-terms", "danger-outline", `data-terms="${row.id}"`)}</div>`).join("")
    + `<div class="form-grid">${input("Effective date", "effective_on", rows.length ? "" : project.start, "date")}
    ${number(project.mode === "hourly" ? "Hourly rate" : "Monthly gross", "rate")}
    ${number("Tax percentage", "tax_pct", 0)}</div>`, async data => {
    await api(path, "POST", data);
    await reload();
  }, "Add pay terms");
  form.querySelectorAll("[data-terms]").forEach(item => item.onclick = () => {
    const row = rows.find(terms => terms.id === Number(item.dataset.terms));
    confirmDelete("pay terms", `Effective ${row.effective_on}`, path + `${row.id}/`);
  });
}
async function hourlyForm(project, cycle) {
  const pref = await api("preferences/");
  modalForm("Record hourly work", `<div class="form-grid">
    ${input("Work date", "work_day", valueDate(pref.timezone), "date")}
    ${number("Hours", "hours")}${input("Location (optional)", "location")}
    ${select("Related task (optional)", "task_id", [["", "No task"], ...(cycle?.plans || []).map(plan => [plan.task_id, plan.name])])}</div>`,
  async data => {
    await api(projectPath(project.id) + "ledger/hourly/", "POST", sparse(data));
    await reload();
  });
}
async function monthlyForm(project) {
  const pref = await api("preferences/");
  modalForm("Record partial month", `<div class="form-grid">
    ${input("Month", "month", valueDate(pref.timezone).slice(0, 7), "month")}
    ${number("Gross amount", "gross")}</div>`, async data => {
    await api(projectPath(project.id) + "ledger/monthly/", "POST", {...data, month: data.month + "-01"});
    await reload();
  });
}
async function paymentForm(project, item) {
  const pref = await api("preferences/");
  modalForm("Record payment", `<p>${escape(item.remaining)} ${escape(project.currency)} remaining</p>
    <div class="form-grid">${input("Receipt date", "received_on", valueDate(pref.timezone), "date")}
    ${number("Amount received", "amount", item.remaining)}</div>`, async data => {
    await api(projectPath(project.id) + `ledger/${item.id}/payments/`, "POST", data);
    await reload();
  });
}
async function preferences() {
  const pref = await api("preferences/");
  const form = modalForm("Profile and preferences", `<div class="form-grid">
    ${input("Name", "name", pref.name)}${number("Age", "age", pref.age)}${input("Qualification", "qualification", pref.qualification)}
    ${input("Specialization", "specialization", pref.specialization)}${input("Timezone", "timezone", pref.timezone)}
    ${input("Default currency", "currency", pref.currency)}${number("Default cycle interval", "interval", pref.interval)}
    ${select("Default interval unit", "interval_unit", units, pref.interval_unit)}
    ${input("Reminder time", "reminder_time", pref.reminder_time.slice(0, 5), "time")}</div>
    <p class="muted">Cycle defaults apply to new projects.</p>${button("Manage review reasons", "reasons")}`, async data => {
    await api("preferences/", "PATCH", {...data, age: data.age || null});
    await reload();
  });
  form.querySelector("[data-action=reasons]").onclick = safe(reasonPicker);
}
async function reasonPicker() {
  const rows = await api("reasons/");
  const form = modalForm("Review reasons", select("Reason", "id", [["", "Add a reason"],
    ...rows.map(row => [row.id, row.label + (row.active ? "" : " (disabled)")])]), async () => {}, "Continue");
  form.onsubmit = event => {
    event.preventDefault();
    const id = Number(toData(form).id);
    const row = rows.find(item => item.id === id);
    modalForm(row ? "Edit reason" : "Add reason", input("Label", "label", row?.label)
      + `<label class="check"><input type="checkbox" name="active" ${row?.active === false ? "" : "checked"}>Active</label>`,
    async data => {
      await api(row ? `reasons/${row.id}/` : "reasons/", row ? "PATCH" : "POST",
        {label: data.label, active: data.active === "on"});
      await reload();
    });
  };
}
async function notifications() {
  const rows = await api("notifications/");
  const form = modalForm("Notifications", rows.map(row => `<div class="line builder-row">
    <p>${escape(row.project)} · Review due ${row.review_on}${row.read_at ? "" : " · New"}</p>
    <button type="button" data-notification="${row.id}">View project</button></div>`).join("") ||
    "<p>No notifications yet.</p>", async () => {}, "Done");
  form.querySelectorAll("[data-notification]").forEach(item => item.onclick = safe(async () => {
    const row = rows.find(notification => notification.id === Number(item.dataset.notification));
    await api(`notifications/${row.id}/read/`, "POST", {});
    selected = row.project_id;
    selectedCycle = row.cycle_id;
    filters.reset();
    modal.close();
    await reload();
  }));
}
filters.onsubmit = event => event.preventDefault();
filters.onchange = safe(reload);
let filterDelay;
filters.querySelector("[name=q]").oninput = () => {
  clearTimeout(filterDelay);
  filterDelay = setTimeout(safe(reload), 200);
};
document.querySelector("#new-project").onclick = safe(() => projectForm());
document.querySelector("#preferences").onclick = safe(preferences);
document.querySelector("#notifications").onclick = safe(notifications);
safe(reload)();
