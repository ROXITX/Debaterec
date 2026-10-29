/* Result cards: verdict, reasoning, the deterministic constraint audit, the
   full debate transcript, and feedback controls. */

import { icons } from "./icons.js";
import { escapeHTML, toast } from "./effects.js";
import { sendFeedback } from "./api.js";

const CIRCUMFERENCE = 2 * Math.PI * 24;

export function renderResults(host, cards, { sessionId, domain }) {
  host.innerHTML = "";
  cards.forEach((card, index) => {
    const node = buildCard(card, index, { sessionId, domain });
    host.appendChild(node);
  });
  // Animate every score ring on the next frame, after layout has settled.
  requestAnimationFrame(() => {
    host.querySelectorAll("[data-ring]").forEach((ring) => {
      const value = Number(ring.dataset.ring);
      ring.style.strokeDashoffset = String(CIRCUMFERENCE * (1 - value / 10));
    });
  });
}

function buildCard(card, index, ctx) {
  const node = document.createElement("article");
  node.className = `card${index === 0 ? " card--top" : ""}`;
  node.style.animationDelay = `${index * 80}ms`;
  node.style.setProperty("--card-accent", card.accent || "var(--accent)");

  const pros = (card.pros || []).slice(0, 4);
  const cons = (card.cons || []).slice(0, 4);
  const tradeoffs = (card.tradeoffs || []).slice(0, 3);
  const specs = (card.display || []).slice(0, 7);

  node.innerHTML = `
    <div class="card__rank">
      <div class="rank__num">${card.rank}</div>
      <div class="ring">
        <svg viewBox="0 0 54 54" aria-hidden="true">
          <circle class="ring__track" cx="27" cy="27" r="24"></circle>
          <circle class="ring__fill" data-ring="${card.score}" cx="27" cy="27" r="24"
                  stroke-dasharray="${CIRCUMFERENCE}" stroke-dashoffset="${CIRCUMFERENCE}"></circle>
        </svg>
        <div class="ring__value">${Number(card.score).toFixed(1)}</div>
      </div>
      <div class="ring__caption">score</div>
    </div>

    <div class="card__body">
      <div class="card__head">
        <div style="min-width:0">
          <h3 class="card__title">${escapeHTML(card.title)}</h3>
          ${card.subtitle ? `<div class="card__sub">${escapeHTML(card.subtitle)}</div>` : ""}
        </div>
        <div class="card__flags">
          ${card.synthetic ? `<span class="badge badge--synthetic"
            title="A procedurally generated catalogue record, not a real product or title. Turn on 'Curated only' to exclude these.">generated</span>` : ""}
          <span class="badge" data-v="${escapeHTML(card.decision)}">${escapeHTML(card.decision)}</span>
          <span class="badge badge--muted">${Math.round((card.confidence || 0) * 100)}% confidence</span>
        </div>
      </div>

      <p class="card__why">${escapeHTML(card.why)}</p>

      ${renderAudit(card.checks)}

      <div class="split">
        ${column("pro", "Why it works", pros, "plus")}
        ${column("con", "Where it falls short", cons, "minus")}
      </div>

      ${tradeoffs.length ? `<div class="column column--trade tradeoffs">
          <div class="column__label">${icons.scales} What you give up</div>
          <ul>${tradeoffs.map((t) => `<li>${escapeHTML(t)}</li>`).join("")}</ul>
        </div>` : ""}

      <div class="card__tools">
        <button class="tool" data-act="specs" aria-pressed="false">${icons.list} Specifications</button>
        <button class="tool" data-act="debate" aria-pressed="false">${icons.scales} Full debate</button>
        <span style="flex:1"></span>
        <button class="tool tool--liked" data-fb="liked" title="Good recommendation">${icons.up} Good</button>
        <button class="tool tool--liked" data-fb="loved" title="Strong preference">${icons.heart} Love it</button>
        <button class="tool tool--disliked" data-fb="disliked" title="Not relevant">${icons.down} Not for me</button>
        <button class="tool tool--disliked" data-fb="blocked" title="Never show this kind again">${icons.ban} Never again</button>
      </div>

      <div class="detail" data-panel="specs"><div>
        <div class="audit" style="margin-top:14px">
          ${specs.map(([label, value]) => `
            <span class="check"><b style="color:var(--ink-muted);font-weight:600">${escapeHTML(label)}</b>
              <span class="check__actual">${escapeHTML(value)}</span></span>`).join("")}
        </div>
        ${card.description ? `<p style="margin-top:12px;font-size:13px;color:var(--ink-soft);line-height:1.6">
            ${escapeHTML(card.description)}</p>` : ""}
      </div></div>

      <div class="detail" data-panel="debate"><div>
        ${renderTranscript(card)}
        ${renderBreakdown(card.breakdown)}
        <div class="composer">
          <input type="text" placeholder="Tell it what to change — “liked it but I don't want slow-paced ones”" data-comment />
          <button data-send>Teach it</button>
        </div>
      </div></div>
    </div>`;

  wireCard(node, card, ctx);
  return node;
}

function column(kind, label, items, icon) {
  if (!items.length) {
    return `<div class="column column--${kind}">
      <div class="column__label">${icons[icon]} ${label}</div>
      <ul><li style="color:var(--ink-faint)">${
        kind === "con" ? "No material objection was raised." : "Nothing specific could be evidenced."
      }</li></ul></div>`;
  }
  return `<div class="column column--${kind}">
    <div class="column__label">${icons[icon]} ${label}</div>
    <ul>${items.map((t) => `<li>${escapeHTML(t)}</li>`).join("")}</ul>
  </div>`;
}

function renderAudit(checks) {
  if (!checks?.length) return "";
  const mark = { pass: "✓", fail: "✕", unknown: "?" };
  return `<div class="audit">
    ${checks
      .map(
        (c) => `<span class="check${c.hard ? " check--hard" : ""}" data-s="${c.status}"
                      title="${escapeHTML(c.label)} — satisfaction ${(c.degree * 100).toFixed(0)}%">
          <span class="check__mark">${mark[c.status]}</span>
          ${escapeHTML(shorten(c.label))}
          <span class="check__actual">${escapeHTML(c.actual)}</span>
        </span>`
      )
      .join("")}
  </div>`;
}

function renderTranscript(card) {
  const d = card.debate || {};
  const sup = d.supporter || {};
  const crit = d.critic || {};
  const judge = d.judge || {};

  const turn = (kind, title, score, body) => `
    <div class="turn turn--${kind}">
      <div class="turn__head">${title}
        ${score != null ? `<span class="turn__score">${Number(score).toFixed(1)} / 10</span>` : ""}
      </div>
      ${body}
    </div>`;

  const list = (items, fallback) =>
    items?.length
      ? `<ul>${items.map((i) => `<li>${escapeHTML(i)}</li>`).join("")}</ul>`
      : `<p style="color:var(--ink-faint)">${fallback}</p>`;

  return `<div class="transcript" style="margin-top:14px">
    ${turn("supporter", "Supporter — the case for", sup.support_score,
      list([...(sup.fit_points || []), ...(sup.strengths || [])], "No evidenced case could be made.")
      + (sup.evidence_fields?.length
        ? `<p style="margin-top:8px;color:var(--ink-faint);font-size:11.5px">
             Evidence drawn from: ${escapeHTML(sup.evidence_fields.join(", "))}</p>` : ""))}
    ${turn("critic", "Critic — the case against", crit.critic_score,
      list(crit.weaknesses, "The Critic found no material objection.")
      + (crit.unsupported_claims?.length
        ? `<p style="margin-top:8px;color:var(--critic);font-size:11.5px">
             Flagged as unsupported: ${escapeHTML(crit.unsupported_claims.join("; "))}</p>` : ""))}
    ${d.rebuttal ? turn("supporter", "Supporter — rebuttal", null,
      `<p>${escapeHTML(d.rebuttal)}</p>`) : ""}
    ${turn("judge", `Judge — ${escapeHTML(judge.decision || "verdict")}`, judge.final_score,
      `<p>${escapeHTML(judge.reason || "")}</p>`
      + (judge.tradeoffs?.length ? list(judge.tradeoffs, "") : ""))}
  </div>`;
}

function renderBreakdown(breakdown) {
  if (!breakdown) return "";
  const entries = [
    ["retrieval", breakdown.retrieval, "text relevance"],
    ["constraints", breakdown.constraints, "hard + soft satisfaction"],
    ["preferences", breakdown.preferences, "taste match"],
    ["evidence", breakdown.evidence, "how much could be verified"],
    ["supporter", breakdown.supporter, "case strength /10"],
    ["critic", breakdown.critic, "survives scrutiny /10"],
  ];
  return `<div class="breakdown">
    ${entries
      .filter(([, v]) => v != null)
      .map(([k, v, hint]) => `<span class="metric-chip" title="${hint}">${k} <b>${Number(v).toFixed(2)}</b></span>`)
      .join("")}
  </div>`;
}

function shorten(label) {
  return String(label || "")
    .replace(/^(must have |must be |prefers )/, "")
    .replace(/ at most /, " ≤ ")
    .replace(/ at least /, " ≥ ");
}

function wireCard(node, card, ctx) {
  node.querySelectorAll("[data-act]").forEach((button) => {
    button.addEventListener("click", () => {
      const panel = node.querySelector(`[data-panel="${button.dataset.act}"]`);
      const open = panel.dataset.open === "true";
      panel.dataset.open = String(!open);
      button.setAttribute("aria-pressed", String(!open));
    });
  });

  node.querySelectorAll("[data-fb]").forEach((button) => {
    button.addEventListener("click", async () => {
      const action = button.dataset.fb;
      node.querySelectorAll("[data-fb]").forEach((b) => b.setAttribute("aria-pressed", "false"));
      button.setAttribute("aria-pressed", "true");
      try {
        await sendFeedback({
          session_id: ctx.sessionId,
          item_id: card.item_id,
          domain: card.domain || ctx.domain,
          feedback: action,
          comment: "",
        });
        toast(action === "blocked" ? "Noted — it won't suggest that kind again." : "Thanks, that's recorded.");
      } catch (error) {
        toast(`Could not save feedback: ${error.message}`, { icon: "alert" });
      }
    });
  });

  const input = node.querySelector("[data-comment]");
  const send = node.querySelector("[data-send]");
  const submit = async () => {
    const comment = input.value.trim();
    if (!comment) return;
    send.disabled = true;
    try {
      const result = await sendFeedback({
        session_id: ctx.sessionId,
        item_id: card.item_id,
        domain: card.domain || ctx.domain,
        feedback: "liked",
        comment,
      });
      input.value = "";
      toast(result.learned?.length ? `Learned: ${result.learned.join(", ")}` : "Comment recorded.");
    } catch (error) {
      toast(`Could not save that: ${error.message}`, { icon: "alert" });
    } finally {
      send.disabled = false;
    }
  };
  send?.addEventListener("click", submit);
  input?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); submit(); }
  });
}

export function renderMetrics(host, metrics, extra = {}) {
  const cells = [
    ["total time", `${metrics.total_seconds?.toFixed(2)}s`],
    ["catalogue", metrics.catalogue_size],
    ["retrieved", metrics.stage1_candidates],
    ["debated", metrics.debated_candidates],
    ["LLM calls", metrics.llm_calls ?? 0],
    ["debate time", `${metrics.debate_seconds?.toFixed(2)}s`],
    ["diversity", metrics.intra_list_diversity?.toFixed(2)],
    ["reasoning", extra.mode === "llm" ? "language model" : "deterministic"],
  ];
  host.innerHTML = cells
    .filter(([, v]) => v != null && v !== "undefineds")
    .map(
      ([label, value]) => `<div class="metric">
        <div class="metric__value">${escapeHTML(value)}</div>
        <div class="metric__label">${escapeHTML(label)}</div>
      </div>`
    )
    .join("");
  host.classList.remove("hidden");
}
