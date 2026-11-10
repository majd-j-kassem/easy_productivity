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
      await onSave(toData(form), form);
      modal.close();
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
  const chosen = project.cycles.find(row => row.id === selectedCycle) ?? project.cycles[0];
  const results = await Promise.all([
    chosen ? api(`${path}cycles/${chosen.id}/`) : null,
    project.mode === "standard" ? null : api(path + "ledger/"),
    project.status === "closed" ? api(path + "report/") : null,
  ]);
  if (token !== renderToken) return;
  renderProject(project, ...results);
}
function goalCard(goal) {
  const progress = goal.quantity ? Math.min(100, Math.round(goal.actual * 100 / goal.quantity)) : 100;
  const counter = goal.kind === "done" ? (goal.actual || goal.previous_actual ? "Done" : "Pending")
    : `${goal.actual} / ${goal.quantity}`;
  return `<div class="goal"><div class="line"><strong>${escape(goal.name)}</strong><span class="count">${counter}</span></div>
    <progress max="100" value="${progress}" aria-label="${escape(goal.name)}"></progress>
    <small>${goal.cumulative} cumulative · ${goal.remaining_original} remaining against original target</small>
    ${button("Daily entry", "entry", "", `data-target="${goal.id}" data-testid="daily-entry"`)}</div>`;
}
function renderProject(project, cycle, ledger, report) {
  const path = projectPath(project.id);
  const isOpen = project.status === "active";
  const reportSection = report ? `<article class="card"><div class="line"><h2>Final report</h2><div class="actions">
    <a class="button" href="${root + path}report.pdf">Download PDF</a><a class="button" href="${root + path}report.xlsx">Download Excel</a>
    </div></div>${table(["Task", "Goal", "Planned", "Actual", "Gap", "Reason"],
      report.goals.map(row => [row.task, row.goal, row.planned, row.actual, row.gap, row.reason]))}</article>` : "";
  const currentCycle = project.cycles.find(row => !row.closed_at);
  const cycleSection = cycle ? `<article class="card"><div class="line"><h2>Cycle ${cycle.sequence}</h2><span class="pill">${escape(label(cycle.status))}</span></div>
    <div class="cycle-toolbar"><p>${cycle.start} to ${cycle.end}</p>
    ${select("View cycle", "cycle", project.cycles.map(item => [item.id, `Cycle ${item.sequence} · ${item.end}`]), cycle.id)}
    ${select("Filter tasks", "local-status", taskStatuses)}</div>
    <div class="actions">${isOpen && !cycle.closed_at ? button("Add task", "task", "primary", 'data-testid="add-task"') : ""}
    ${cycle.status === "review" && isOpen ? button("Review and close cycle", "review", "primary", 'data-testid="review-cycle"') : ""}</div>
    <div id="plans">${cycle.plans.map(plan => `<section class="task" data-status="${escape(plan.status)}">
      <div class="line"><div><h3>${escape(plan.name)}</h3><small>${escape(plan.kind)} · ${escape(plan.priority)} priority</small></div>
      <span class="pill">${escape(plan.decision || plan.status)}</span></div>
      ${plan.reason ? `<p class="muted">${escape(plan.reason)} ${escape(plan.note)}</p>` : ""}
      ${Object.keys(plan.values).length ? `<dl class="values">${Object.entries(plan.values).map(([key, value]) =>
        `<div><dt>${escape(label(key))}</dt><dd>${escape(value)}</dd></div>`).join("")}</dl>` : ""}
      ${plan.targets.map(goalCard).join("")}
      ${!cycle.closed_at && isOpen && plan.status === "open" ? button("Edit plan", "plan", "", `data-plan="${plan.id}"`) : ""}
      ${!cycle.closed_at && isOpen && plan.status === "open" && plan.targets.every(goal => goal.actual >= goal.quantity)
        ? button("Confirm complete", "complete", "", `data-plan="${plan.id}"`) : ""}</section>`).join("") ||
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
    </article>${reportSection}${cycleSection}${ledger ? ledgerHtml(project, ledger) : ""}`;
  detail.querySelector("[name=cycle]")?.addEventListener("change", safe(async event => {
    selectedCycle = Number(event.target.value);
    await reload();
  }));
  detail.querySelector("[name=local-status]")?.addEventListener("change", event => {
    detail.querySelectorAll("[data-status]").forEach(item => {
      item.hidden = Boolean(event.target.value && item.dataset.status !== event.target.value);
    });
  });
  const actions = {
    "edit-project": () => projectForm(project), kinds: () => kindPicker(project),
    "delete-project": () => modalForm("Delete project?", `<p>Permanently delete <strong>${escape(project.name)}</strong>
      and its tasks, progress, and financial records? This action cannot be undone.</p>`, async () => {
      await api(path, "DELETE");
      selected = null;
      selectedCycle = null;
      detail.replaceChildren();
      message(`Deleted project: ${project.name}`);
      await safe(reload)();
    }, "Delete project", "danger"),
    task: () => taskForm(project), review: () => reviewForm(project, cycle),
    finish: async () => reviewForm(project, currentCycle ? await api(`${path}cycles/${currentCycle.id}/`) : null, true),
    complete: element => modalForm("Confirm task completion", "<p>This closes the task for new daily entries.</p>", async () => {
      await api(path + `plans/${element.dataset.plan}/complete/`, "POST", {});
      await reload();
    }, "Confirm complete"),
    plan: element => planForm(project, cycle.plans.find(plan => plan.id === Number(element.dataset.plan))),
    entry: element => {
      const id = Number(element.dataset.target);
      const plan = cycle.plans.find(row => row.targets.some(target => target.id === id));
      return entryForm(project, cycle, plan, plan.targets.find(target => target.id === id));
    },
    terms: () => termsForm(project), hourly: () => hourlyForm(project, cycle),
    monthly: () => monthlyForm(project),
    payment: element => paymentForm(project, ledger.items.find(item => item.id === Number(element.dataset.receivable))),
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
async function projectForm(project = null) {
  const pref = await api("preferences/");
  modalForm(project ? "Edit project" : "New project", `<div class="form-grid">
    ${input("Project name", "name", project?.name)}
    ${input("Planned end (optional)", "planned_end", project?.planned_end, "date")}
    ${project ? "" : input("Start date", "start", valueDate(pref.timezone), "date") +
      input("First review (optional)", "first_review", "", "date") +
      number("Review interval", "interval", pref.interval) + select("Interval unit", "interval_unit", units, pref.interval_unit) +
      select("Project type", "mode", [["standard", "Standard"], ["hourly", "Hourly income"], ["monthly", "Monthly income"]], "standard") +
      input("Financial project currency", "currency", pref.currency)}</div>`, async data => {
    const result = project ? await api(projectPath(project.id), "PATCH", {...data, planned_end: data.planned_end || null})
      : await api("projects/", "POST", sparse(data));
    selected = result.id;
    selectedCycle = null;
    await reload();
  });
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
function taskForm(project) {
  if (!project.kinds.length) return kindForm(project);
  const form = modalForm("New task", `<div class="form-grid">${input("Task name", "name")}
    ${select("Type", "kind_id", project.kinds.map(kind => [kind.id, kind.name]))}
    ${select("Priority", "priority", priorities, "normal")}</div>
    <div class="form-grid" data-values></div>
    <fieldset><legend>Goals</legend><div data-goals></div>${button("Add goal", "add-goal")}</fieldset>`,
    async ({name, kind_id, priority}) => {
      const goals = Array.from(form.querySelectorAll(".builder-row")).map(row => {
        const goal = fieldValues(row);
        if (goal.kind === "done") goal.quantity = 1;
        return goal;
      });
      await api(projectPath(project.id) + "tasks/", "POST", {name, kind_id, priority, goals,
        values: fieldValues(form.querySelector("[data-values]"))});
      await reload();
    });
  const type = form.querySelector("[name=kind_id]");
  const fields = () => {
    const kind = project.kinds.find(item => item.id === Number(type.value));
    form.querySelector("[data-values]").innerHTML = fieldRows(kind.task_fields);
  };
  type.onchange = fields;
  fields();
  function addGoal() {
    const row = document.createElement("div");
    row.className = "builder-row";
    row.innerHTML = `<div class="form-grid">${input("Goal name", "name")}${input("Metric (e.g. Test cases)", "metric")}
      ${select("Measurement", "kind", [["count", "Count outputs"], ["done", "Done"]])}
      ${number("Target quantity", "quantity", 1)}</div><button type="button" data-remove>Remove goal</button>`;
    const kind = row.querySelector("[name=kind]");
    kind.onchange = () => row.querySelector("[name=quantity]").closest("label").hidden = kind.value === "done";
    row.querySelector("[data-remove]").onclick = () => row.remove();
    form.querySelector("[data-goals]").append(row);
  }
  form.querySelector("[data-action=add-goal]").onclick = addGoal;
  addGoal();
}
function planForm(project, plan) {
  modalForm("Edit cycle plan", `${select("Priority", "priority", priorities, plan.priority)}
    ${plan.targets.filter(target => target.kind === "count").map(target =>
    number(`Target for ${target.name}`, `target-${target.id}`, target.quantity)).join("")}`,
  async data => {
    const targets = Object.fromEntries(Object.entries(data).filter(([key]) => key.startsWith("target-"))
      .map(([key, value]) => [key.slice(7), value]));
    await api(projectPath(project.id) + `plans/${plan.id}/`, "PATCH", {priority: data.priority, targets});
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
    ${item.payments.length ? table(["Receipt date", "Amount"], item.payments.map(payment => [payment.received_on, payment.amount])) : ""}
    ${project.status !== "closed" && Number(item.remaining) > 0 ? button("Record payment", "payment", "", `data-receivable="${item.id}"`) : ""}</li>`).join("");
  return `<article class="card"><div class="line"><h2>Income ledger · ${escape(ledger.currency)}</h2><span class="pill">${escape(ledger.remaining)} remaining</span></div>
    <div class="actions">${active ? button("Pay terms", "terms") + (project.mode === "hourly"
      ? button("Record hourly work", "hourly", "primary") : button("Record partial month", "monthly", "primary")) : ""}</div>
    <h3>Received by month</h3>${table(["Month", "Received"], Object.entries(ledger.received_by_month).sort().reverse())}
    <h3>Receivables</h3>${rows ? `<ul class="ledger-list">${rows}</ul>` : '<p class="muted">No receivables yet.</p>'}</article>`;
}
async function termsForm(project) {
  const path = projectPath(project.id) + "terms/";
  const rows = await api(path);
  modalForm("Pay terms", table(["Effective from", "Rate", "Tax %"], rows.map(row => [row.effective_on, row.rate, row.tax_pct]))
    + `<div class="form-grid">${input("Effective date", "effective_on", rows.length ? "" : project.start, "date")}
    ${number(project.mode === "hourly" ? "Hourly rate" : "Monthly gross", "rate")}
    ${number("Tax percentage", "tax_pct", 0)}</div>`, async data => {
    await api(path, "POST", data);
    await reload();
  }, "Add pay terms");
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
