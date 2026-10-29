/* Renders the NLP layer's output and the pipeline trace.

   This section exists because the extraction step is where the system is most
   likely to be wrong, and where a person can most easily correct it. Showing
   the constraints as chips — hard ones in red, soft in accent, each labelled
   with whether a rule or the model found it — turns an opaque step into
   something reviewable. */

import { escapeHTML } from "./effects.js";

const STEPS = [
  { key: "understanding", label: "Understanding" },
  { key: "retrieval", label: "Retrieval" },
  { key: "debate", label: "Debate" },
  { key: "ranking", label: "Ranking" },
];

export function renderTrace(host) {
  host.innerHTML = STEPS.map(
    (step) => `
    <div class="trace__step" data-step="${step.key}" data-state="idle">
      <span class="trace__dot"></span>
      <span>${step.label}</span>
      <span class="trace__time" data-time></span>
    </div>`
  ).join("");
}

export function markStep(host, key, state, seconds) {
  const node = host.querySelector(`[data-step="${key}"]`);
  if (!node) return;
  node.dataset.state = state;
  if (seconds != null) {
    const slot = node.querySelector("[data-time]");
    if (slot) slot.textContent = `${(seconds * 1000).toFixed(0)}ms`;
  }
}

export function renderUnderstanding(host, payload, meta) {
  const { domain_label: label, accent, count } = meta;
  const confidence = Math.round((payload.domain_confidence || 0) * 100);
  const source = payload.domain_source === "user" ? "you chose it"
    : payload.domain_source === "llm" ? "model-classified"
    : "rule-matched";

  const constraints = payload.constraints || [];
  const hard = constraints.filter((c) => c.hard);
  const soft = constraints.filter((c) => !c.hard);

  const chip = (c) => `
    <span class="pill ${c.hard ? "pill--hard" : "pill--soft"}" style="animation-delay:${Math.random() * 160}ms">
      <span class="pill__kind">${c.hard ? "must" : "prefers"}</span>
      ${escapeHTML(stripPrefix(c.text))}
      <span class="pill__src">${escapeHTML(c.source)}</span>
    </span>`;

  host.innerHTML = `
    <div class="understanding__row">
      <span class="pill pill--domain" style="--accent:${accent}">
        ${escapeHTML(label)}${count ? ` · ${count} items` : ""}
      </span>
      <span class="pill">${confidence}% confident · ${source}</span>
      <span class="pill">${constraints.length} constraint${constraints.length === 1 ? "" : "s"} extracted</span>
      <span class="pill">${escapeHTML(sourceLabel(payload.extraction_source))}</span>
    </div>
    ${hard.length ? `<div class="understanding__row">
        <span class="eyebrow" style="min-width:96px">Requirements</span>${hard.map(chip).join("")}
      </div>` : ""}
    ${soft.length ? `<div class="understanding__row">
        <span class="eyebrow" style="min-width:96px">Preferences</span>${soft.map(chip).join("")}
      </div>` : ""}
    ${payload.ambiguities?.length ? `<div class="understanding__row">
        <span class="eyebrow" style="min-width:96px">Unclear</span>
        ${payload.ambiguities.map((a) => `<span class="pill">${escapeHTML(a)}</span>`).join("")}
      </div>` : ""}
  `;
}

export function renderShortlist(host, shortlist) {
  if (!shortlist?.length) return;
  const row = document.createElement("div");
  row.className = "understanding__row";
  row.innerHTML = `
    <span class="eyebrow" style="min-width:96px">Shortlist</span>
    ${shortlist
      .map(
        (c, i) => `<span class="pill" style="animation-delay:${i * 45}ms">
            <span class="pill__kind">${(c.score).toFixed(2)}</span>${escapeHTML(c.title)}
          </span>`
      )
      .join("")}`;
  host.appendChild(row);
}

function stripPrefix(text) {
  return String(text || "").replace(/^(must have |must be |prefers )/, "");
}

function sourceLabel(source) {
  if (source === "hybrid") return "rules + language model";
  if (source === "llm") return "language model";
  return "rule-based extraction";
}
