const API = "/api/v1";
const KINDS = [
  { kind: "character", key: "characters", title: "Characters" },
  { kind: "location", key: "locations", title: "Locations" },
  { kind: "object", key: "objects", title: "Objects" },
];

const seriesSelect = document.getElementById("series");
const onlyReview = document.getElementById("onlyReview");
const content = document.getElementById("content");
const errorBox = document.getElementById("error");
let data = null;
let editing = null; // "kind:id" of the card with its edit form open

// All story-derived text goes in through textContent, never innerHTML.
function el(tag, props = {}, ...children) {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(props)) {
    if (name === "class") node.className = value;
    else if (name.startsWith("on")) node.addEventListener(name.slice(2), value);
    else node[name] = value;
  }
  for (const child of children) node.append(child);
  return node;
}

function showError(message) {
  errorBox.textContent = message || "";
  errorBox.hidden = !message;
}

async function api(path, options = {}) {
  const response = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try { detail = (await response.json()).detail || detail; } catch (_) { /* keep statusText */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return response.json();
}

async function act(request) {
  showError("");
  try {
    await request();
    await load();
  } catch (error) {
    showError(error.message);
  }
}

async function loadSeries() {
  // List endpoints return { count, items }.
  const projects = (await api("/projects")).items;
  const wanted = new URLSearchParams(location.search).get("series");
  for (const project of projects) {
    for (const series of (await api(`/projects/${project.id}/series`)).items) {
      seriesSelect.append(new Option(`${project.title} / ${series.title}`, series.id, false, series.id === wanted));
    }
  }
}

async function load() {
  if (!seriesSelect.value) {
    content.replaceChildren(el("p", { class: "muted", textContent: "No series yet." }));
    return;
  }
  data = await api(`/series/${seriesSelect.value}/entities`);
  render();
}

function render() {
  content.replaceChildren();
  for (const { kind, key, title } of KINDS) {
    const all = data[key];
    const active = all.filter((e) => !e.merged_into_id);
    const merged = all.filter((e) => e.merged_into_id);
    const shown = onlyReview.checked ? active.filter((e) => e.review_status === "needs_review") : active;
    content.append(el("h2", { textContent: `${title} (${shown.length}${onlyReview.checked ? ` of ${active.length}` : ""})` }));
    if (!shown.length) content.append(el("p", { class: "muted", textContent: "Nothing here." }));
    for (const entity of shown) content.append(card(kind, entity, active));
    for (const entity of merged) content.append(mergedCard(kind, entity, all));
  }
}

function badge(entity) {
  const labels = { auto: ["auto", "grey"], needs_review: ["needs review", "warn"], approved: ["approved", "ok"], stale: ["not in latest run", "grey"] };
  const [text, tone] = labels[entity.review_status] || [entity.review_status, "grey"];
  return el("span", { class: `chip ${tone}`, textContent: text });
}

function card(kind, entity, siblings) {
  const node = el("div", { class: `card ${entity.review_status}` });
  const head = el("div", { class: "head" }, el("span", { class: "name", textContent: entity.name }));
  if (entity.disambiguation) head.append(el("span", { class: "chip", textContent: entity.disambiguation }));
  head.append(badge(entity));
  if (entity.locked) head.append(el("span", { class: "chip grey", textContent: "locked" }));
  head.append(el("span", { class: "muted", textContent: `${entity.verified_mention_count}/${entity.mention_count} quotes verified` }));
  node.append(head);
  if (entity.description) node.append(el("div", { textContent: entity.description }));
  if (entity.aliases.length) node.append(el("div", { class: "muted", textContent: `Also called: ${entity.aliases.join(", ")}` }));
  if (entity.review_note) node.append(el("div", { class: "note", textContent: entity.review_note }));

  if (editing === `${kind}:${entity.id}`) {
    node.append(editForm(kind, entity));
  } else {
    node.append(actions(kind, entity, siblings));
  }
  return node;
}

function actions(kind, entity, siblings) {
  const bar = el("div", { class: "actions" });
  if (entity.review_status !== "approved") {
    bar.append(el("button", {
      class: "primary", textContent: "Approve",
      onclick: () => act(() => api(`/entities/${kind}/${entity.id}`, { method: "PATCH", body: JSON.stringify({ review_status: "approved" }) })),
    }));
  }
  bar.append(el("button", { textContent: "Edit", onclick: () => { editing = `${kind}:${entity.id}`; render(); } }));

  const targets = siblings.filter((other) => other.id !== entity.id);
  if (targets.length) {
    const select = el("select");
    select.append(new Option("Merge into...", ""));
    for (const other of targets) select.append(new Option(other.disambiguation ? `${other.name} (${other.disambiguation})` : other.name, other.id));
    bar.append(select, el("button", {
      textContent: "Merge",
      onclick: () => select.value && act(() => api(`/entities/${kind}/${entity.id}/merge`, { method: "POST", body: JSON.stringify({ into_id: select.value }) })),
    }));
  }
  return bar;
}

function editForm(kind, entity) {
  const name = el("input", { value: entity.name, placeholder: "Name" });
  const label = el("input", { value: entity.disambiguation, placeholder: "Label that tells same-named entries apart (for example: son)" });
  const description = el("textarea", { value: entity.description || "", placeholder: "Description" });
  return el("div", { class: "form" }, name, label, description, el("div", { class: "actions" },
    el("button", {
      class: "primary", textContent: "Save",
      onclick: () => act(async () => {
        await api(`/entities/${kind}/${entity.id}`, {
          method: "PATCH",
          body: JSON.stringify({ name: name.value, disambiguation: label.value, description: description.value }),
        });
        editing = null;
      }),
    }),
    el("button", { textContent: "Cancel", onclick: () => { editing = null; render(); } }),
  ));
}

function mergedCard(kind, entity, all) {
  const target = all.find((other) => other.id === entity.merged_into_id);
  return el("div", { class: "card merged" },
    el("div", { class: "head" },
      el("span", { class: "name", textContent: entity.name }),
      el("span", { class: "chip grey", textContent: `merged into ${target ? target.name : "another entry"}` }),
      el("button", { textContent: "Unmerge", onclick: () => act(() => api(`/entities/${kind}/${entity.id}/unmerge`, { method: "POST" })) }),
    ));
}

seriesSelect.addEventListener("change", () => act(async () => {}));
onlyReview.addEventListener("change", () => data && render());
document.getElementById("refresh").addEventListener("click", () => act(async () => {}));

loadSeries().then(load).catch((error) => showError(error.message));
