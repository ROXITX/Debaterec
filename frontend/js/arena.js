/* The live three-lane debate arena.

   One lane per role. A chip appears in a lane the instant that agent's call is
   dispatched and fills in when the reply lands, so the sequence on screen is
   the sequence in the pipeline — Supporters first, then Critics responding to
   them, then the Judge. */

import { icons } from "./icons.js";
import { escapeHTML } from "./effects.js";

const LANES = [
  {
    key: "supporter",
    title: "Supporter",
    role: "Argues why it fits",
    icon: "plus",
    empty: "Waiting for candidates to arrive from retrieval.",
  },
  {
    key: "critic",
    title: "Critic",
    role: "Challenges the case",
    icon: "minus",
    empty: "Listens first — responds once the Supporter has spoken.",
  },
  {
    key: "judge",
    title: "Judge",
    role: "Weighs both sides",
    icon: "gavel",
    empty: "Rules only after both sides have argued.",
  },
];

export class Arena {
  constructor(host) {
    this.host = host;
    this.chips = new Map(); // `${role}:${itemId}` -> element
    this.counts = { supporter: 0, critic: 0, judge: 0 };
  }

  mount() {
    this.chips.clear();
    this.counts = { supporter: 0, critic: 0, judge: 0 };
    this.host.innerHTML = LANES.map(
      (lane) => `
      <div class="lane lane--${lane.key}" data-lane="${lane.key}" data-active="false">
        <div class="lane__head">
          <div class="lane__icon">${icons[lane.icon]}</div>
          <div>
            <div class="lane__title">${lane.title}</div>
            <div class="lane__role">${lane.role}</div>
          </div>
          <div class="lane__count" data-count>0</div>
        </div>
        <div class="lane__body" data-body>
          <div class="lane__empty">${lane.empty}</div>
        </div>
      </div>`
    ).join("");
  }

  lane(role) {
    return this.host.querySelector(`[data-lane="${role}"]`);
  }

  setActive(role, active) {
    const lane = this.lane(role);
    if (lane) lane.dataset.active = String(active);
  }

  /** An agent call has gone out: show a placeholder that is visibly working. */
  thinking(role, { item_id: itemId, title }) {
    const lane = this.lane(role);
    if (!lane) return;
    const body = lane.querySelector("[data-body]");
    const empty = body.querySelector(".lane__empty");
    if (empty) empty.remove();

    const key = `${role}:${itemId}`;
    if (this.chips.has(key)) return;

    const chip = document.createElement("article");
    chip.className = "arg";
    chip.dataset.status = "thinking";
    chip.innerHTML = `
      <div class="arg__top">
        <div class="arg__title">${escapeHTML(title)}</div>
      </div>
      <div class="think">
        <span class="dots"><i></i><i></i><i></i></span>
        <span class="think__bar"></span>
        <span class="think__label">${labelFor(role)}</span>
      </div>`;
    body.appendChild(chip);
    this.chips.set(key, chip);
  }

  /** The reply landed: swap the placeholder for the actual argument. */
  done(role, event) {
    const key = `${role}:${event.item_id}`;
    const chip = this.chips.get(key);
    if (!chip) {
      this.thinking(role, event);
      return this.done(role, event);
    }

    const payload = event.payload || {};
    const points = (payload.points || []).slice(0, 3);
    const score = payload.score;

    chip.dataset.status = "done";
    chip.innerHTML = `
      <div class="arg__top">
        <div class="arg__title">${escapeHTML(event.title)}</div>
        ${score != null ? `<div class="arg__score">${Number(score).toFixed(1)}</div>` : ""}
      </div>
      ${points.length ? `<ul class="arg__points">${points.map((p) => `<li>${escapeHTML(p)}</li>`).join("")}</ul>` : ""}
      ${payload.decision ? `<span class="arg__verdict" data-v="${escapeHTML(payload.decision)}">
          ${escapeHTML(payload.decision)}${payload.confidence != null
            ? ` · ${Math.round(payload.confidence * 100)}% sure` : ""}
        </span>` : ""}
      ${payload.flags?.length ? `<span class="arg__verdict" data-v="reject" title="Dataset text that looked like an instruction">
          ${payload.flags.length} flagged
        </span>` : ""}`;

    this.counts[role] = (this.counts[role] || 0) + 1;
    const counter = this.lane(role)?.querySelector("[data-count]");
    if (counter) counter.textContent = String(this.counts[role]);
  }

  /** A rebuttal is appended to the Supporter's existing chip. */
  rebuttal(event) {
    const chip = this.chips.get(`supporter:${event.item_id}`);
    if (!chip || !event.payload?.rebuttal) return;
    const line = document.createElement("ul");
    line.className = "arg__points";
    line.innerHTML = `<li><strong>Rebuttal:</strong> ${escapeHTML(event.payload.rebuttal)}</li>`;
    chip.appendChild(line);
  }

  finish() {
    LANES.forEach((lane) => this.setActive(lane.key, false));
  }
}

function labelFor(role) {
  if (role === "supporter") return "building the case";
  if (role === "critic") return "looking for problems";
  return "weighing both sides";
}
