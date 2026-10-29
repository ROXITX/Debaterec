/* Application wiring: state, event routing and the submit flow. */

import { health, domains, streamRecommendation, getJSON } from "./api.js";
import { icons, domainIcon } from "./icons.js";
import {
  setAccent, burstFrom, toast, notice, clearNotices, reveal, escapeHTML,
} from "./effects.js";
import { renderTrace, markStep, renderUnderstanding, renderShortlist } from "./understanding.js";
import { Arena } from "./arena.js";
import { renderResults, renderMetrics } from "./results.js";

const el = (id) => document.getElementById(id);

const state = {
  domain: "auto",
  catalogue: [],
  curatedOnly: false,
  running: false,
  stream: null,
  sessionId: loadSession(),
  clock: null,
  startedAt: 0,
};

const arena = new Arena(el("arena"));

/* ---------------------------------------------------------------- bootstrap */

async function boot() {
  el("brandMark").innerHTML = icons.scales;
  renderTrace(el("trace"));
  arena.mount();
  wireForm();

  wireAuroraFade();
  wireCuratedToggle();
  
  const select = el("modelSelect");
  const ollamaSelect = el("ollamaModelSelect");

  async function applyProvider(provider, model) {
    select.disabled = true;
    ollamaSelect.disabled = true;
    el("statusText").textContent = "switching…";
    try {
      const body = { provider };
      if (provider === "ollama" && model) body.model = model;
      const res = await fetch("/api/settings/llm", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const info = await res.json();
      showStatus(info);
      const label = select.options[select.selectedIndex].text;
      toast(model ? `Switched to ${label} · ${model}` : `Switched to ${label}`);
    } catch (e) {
      notice("Failed to change the reasoning backend.", "error");
    } finally {
      select.disabled = false;
      ollamaSelect.disabled = false;
    }
  }

  // Offline mode needs a second choice: which locally-pulled model to run.
  // We fetch the list from the daemon so the dropdown reflects what is really
  // installed rather than a hardcoded name that may not be pulled.
  async function populateOllamaModels() {
    try {
      const data = await getJSON("/api/ollama/models");
      if (!data.reachable || !data.models.length) {
        ollamaSelect.hidden = true;
        if (!data.reachable) {
          notice(
            "Offline mode needs Ollama running. Start it with 'ollama serve' " +
            "(or launch via start.bat), then reselect Offline.",
            "error"
          );
        } else {
          notice("Ollama is running but no models are pulled. Run: ollama pull llama3.1:8b", "error");
        }
        return;
      }
      ollamaSelect.innerHTML = data.models
        .map((m) => `<option value="${m}" style="color:#000">${m}</option>`)
        .join("");
      ollamaSelect.value = data.models.includes(data.current) ? data.current : data.models[0];
      ollamaSelect.hidden = false;
    } catch {
      ollamaSelect.hidden = true;
    }
  }

  select.addEventListener("change", async () => {
    if (select.value === "ollama") {
      await populateOllamaModels();
      await applyProvider("ollama", ollamaSelect.hidden ? null : ollamaSelect.value);
    } else {
      ollamaSelect.hidden = true;
      await applyProvider(select.value);
    }
  });

  ollamaSelect.addEventListener("change", () => applyProvider("ollama", ollamaSelect.value));

  try {
    const [{ domains: list }, info] = await Promise.all([domains(), health()]);
    state.catalogue = list;
    renderRail(list);
    renderExamples(list);
    showStatus(info);
  } catch (error) {
    showStatus(null, error);
    notice(
      "Could not reach the backend. Make sure the server is running, then reload this page.",
      "error"
    );
  }
}

/**
 * The aurora is anchored to the viewport so the domain colour is always
 * present, but at full strength it competes with dense text further down the
 * page. Fading it out as the reader scrolls keeps the atmosphere at the top and
 * the contrast where the actual content is.
 */
function wireAuroraFade() {
  const aurora = document.getElementById("aurora");
  if (!aurora) return;
  let queued = false;
  const update = () => {
    queued = false;
    const progress = Math.min(1, window.scrollY / 760);
    aurora.style.opacity = String(1 - progress * 0.72);
  };
  window.addEventListener("scroll", () => {
    if (queued) return;
    queued = true;
    requestAnimationFrame(update);
  }, { passive: true });
  update();
}

function wireCuratedToggle() {
  const button = el("curatedToggle");
  if (!button) return;
  button.addEventListener("click", () => {
    state.curatedOnly = !state.curatedOnly;
    button.setAttribute("aria-pressed", String(state.curatedOnly));
    toast(state.curatedOnly
      ? "Searching hand-checked records only."
      : "Searching the full catalogue, including generated records.");
  });
}

function showStatus(info, error) {
  const node = el("status");
  const text = el("statusText");
  if (error || !info) {
    node.dataset.live = "offline";
    text.textContent = "backend unreachable";
    return;
  }
  const provider = info.provider || "";
  const live = !/deterministic|no GEMINI|unavailable/i.test(provider);
  node.dataset.live = live ? "true" : "offline";
  text.textContent = live ? provider : "deterministic mode — no API key";
  node.title = live
    ? `Reasoning with ${provider}`
    : "No LLM configured. The debate still runs, using the deterministic rule-based agents. "
      + "Add GEMINI_API_KEY to .env for model-written arguments.";
      
  const select = el("modelSelect");
  const ollamaSelect = el("ollamaModelSelect");
  if (provider.includes("gemini")) select.value = "gemini";
  else if (provider.includes("ollama")) select.value = "ollama";
  else select.value = "mock";

  // Show the local-model picker only while offline mode is the active backend.
  if (ollamaSelect) ollamaSelect.hidden = !provider.includes("ollama");
}

/* --------------------------------------------------------------- domain rail */

function renderRail(list) {
  const rail = el("rail");
  const auto = `
    <button class="chip" type="button" data-domain="auto" aria-pressed="true">
      ${icons.spark}<span>Detect automatically</span>
    </button>`;
  rail.innerHTML = auto + list
    .map(
      (d) => `<button class="chip" type="button" data-domain="${d.key}" aria-pressed="false"
                      style="--chip-tint:${hexA(d.accent, 0.16)};--chip-line:${hexA(d.accent, 0.45)}">
          ${domainIcon(d.icon)}<span>${escapeHTML(d.label)}</span>
          <span class="chip__count">${d.count}</span>
        </button>`
    )
    .join("");

  rail.querySelectorAll("[data-domain]").forEach((chip) => {
    chip.addEventListener("click", () => {
      state.domain = chip.dataset.domain;
      rail.querySelectorAll("[data-domain]").forEach((c) =>
        c.setAttribute("aria-pressed", String(c === chip))
      );
      const picked = list.find((d) => d.key === state.domain);
      setAccent(picked ? picked.accent : "#7c5cff", { flash: true });
      el("domainHint").textContent = picked
        ? `Searching ${picked.count} ${picked.label.toLowerCase()}`
        : "Domain detected automatically";
      renderExamples(list);
    });
  });
}

function renderExamples(list) {
  const host = el("examples");
  const pool = state.domain === "auto"
    ? list.flatMap((d) => d.examples.slice(0, 1))
    : (list.find((d) => d.key === state.domain)?.examples || []);

  host.innerHTML = pool
    .slice(0, 4)
    .map((text) => `<button class="example" type="button">${escapeHTML(text)}</button>`)
    .join("");

  host.querySelectorAll(".example").forEach((button) => {
    button.addEventListener("click", () => {
      el("query").value = button.textContent.replace(/^[“"]|[”"]$/g, "");
      autosize(el("query"));
      el("query").focus();
    });
  });
}

/* ------------------------------------------------------------------ the form */

function wireForm() {
  const form = el("form");
  const input = el("query");

  input.addEventListener("input", () => autosize(input));
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      form.requestSubmit();
    }
  });

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    run(input.value.trim());
  });
}

function autosize(node) {
  node.style.height = "auto";
  node.style.height = `${Math.min(node.scrollHeight, 160)}px`;
}

/* ---------------------------------------------------------------- the request */

function run(query) {
  if (!query) {
    el("query").focus();
    return;
  }
  if (state.running) {
    state.stream?.close();
  }

  clearNotices();
  burstFrom(el("submit"), { sparks: 26 });
  setRunning(true);

  arena.mount();
  el("results").innerHTML = "";
  el("metrics").classList.add("hidden");
  el("understanding").innerHTML = "";
  renderTrace(el("trace"));
  reveal(el("understandStage"));
  reveal(el("arenaStage"));
  el("resultsStage").classList.add("hidden");

  state.startedAt = performance.now();
  startClock();
  el("understandStage").scrollIntoView({ behavior: "smooth", block: "start" });

  state.stream = streamRecommendation(
    {
      query,
      domain: state.domain,
      topK: 5,
      method: "debate",
      sessionId: state.sessionId,
      curatedOnly: state.curatedOnly,
    },
    handleEvent,
    (error) => {
      notice(error.message, "error");
      setRunning(false);
      stopClock();
    }
  );
}

function handleEvent(event) {
  switch (event.type) {
    case "stage":       return onStage(event);
    case "round":       return onRound(event);
    case "agent":       return onAgent(event);
    case "result":      return undefined; // cards are rendered together on "done"
    case "notice":      return notice(event.message);
    case "timing":      return undefined;
    case "error":       return onError(event);
    case "done":        return onDone(event);
    default:            return undefined;
  }
}

function onStage(event) {
  const trace = el("trace");
  if (event.status === "start") {
    markStep(trace, event.stage, "active");
    if (event.stage === "debate") {
      el("arenaNote").textContent = `${event.label} · ${
        event.mode === "llm" ? event.provider : "deterministic agents"
      }`;
    }
    return;
  }

  markStep(trace, event.stage, "done", event.seconds);

  if (event.stage === "understanding") {
    const meta = state.catalogue.find((d) => d.key === event.domain);
    setAccent(event.accent, { flash: true });
    renderUnderstanding(el("understanding"), event.understanding, {
      domain_label: event.domain_label,
      accent: event.accent,
      count: meta?.count,
    });
    el("understandNote").textContent =
      `${event.domain_label} · ${(event.seconds * 1000).toFixed(0)}ms`;
    state.lastDomain = event.domain;
  }

  if (event.stage === "retrieval") {
    renderShortlist(el("understanding"), event.shortlist);
    const parts = [`${event.pool} in catalogue`, `${event.stage1} retrieved`];
    if (event.filtered_out) parts.push(`${event.filtered_out} removed by hard filters`);
    el("understandNote").textContent += ` · ${parts.join(" · ")}`;
  }
}

function onRound(event) {
  if (event.status === "start") {
    arena.setActive(event.round === "rebuttal" ? "supporter" : event.round, true);
  } else {
    arena.setActive(event.round === "rebuttal" ? "supporter" : event.round, false);
  }
}

function onAgent(event) {
  if (event.role === "rebuttal") return arena.rebuttal(event);
  if (event.status === "thinking") return arena.thinking(event.role, event);
  return arena.done(event.role, event);
}

function onError(event) {
  notice(event.message, "error");
  setRunning(false);
  stopClock();
}

function onDone(event) {
  stopClock();
  arena.finish();
  setRunning(false);

  reveal(el("resultsStage"));
  renderResults(el("results"), event.results, {
    sessionId: state.sessionId,
    domain: event.domain,
  });
  renderMetrics(el("metrics"), event.metrics, { mode: event.mode });

  const m = event.metrics;
  el("resultsNote").textContent =
    `Top ${event.results.length} of ${m.debated_candidates} debated, from ${m.catalogue_size} ${event.domain_label.toLowerCase()}`;

  // If the debate was effectively instant there was nothing to watch, so take
  // the person straight to the answer. If it took real time they were watching
  // the arena, and yanking the page out from under them would be rude.
  if (m.debate_seconds < 1.2) {
    el("resultsStage").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  toast(`${event.results.length} recommendations ready in ${m.total_seconds.toFixed(1)}s`);
}

/* --------------------------------------------------------------------- chrome */

function setRunning(running) {
  state.running = running;
  const button = el("submit");
  button.disabled = running;
  el("submitLabel").textContent = running ? "Debating…" : "Start the debate";
  if (!running) button.innerHTML = `<span id="submitLabel">Start the debate</span>${icons.send}`;
}

function startClock() {
  stopClock();
  state.clock = window.setInterval(() => {
    const seconds = (performance.now() - state.startedAt) / 1000;
    el("arenaClock").textContent = `${seconds.toFixed(1)}s`;
  }, 100);
}

function stopClock() {
  if (state.clock) window.clearInterval(state.clock);
  state.clock = null;
}

function hexA(hex, alpha) {
  const clean = String(hex || "#7c5cff").replace("#", "");
  const value = parseInt(clean, 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

function loadSession() {
  // sessionStorage keeps preference memory scoped to this tab and this visit,
  // which is the least surprising behaviour for a demo people will share.
  try {
    let id = sessionStorage.getItem("debaterec.session");
    if (!id) {
      id = `s-${Math.random().toString(36).slice(2, 10)}`;
      sessionStorage.setItem("debaterec.session", id);
    }
    return id;
  } catch {
    return `s-${Math.random().toString(36).slice(2, 10)}`;
  }
}

boot();
