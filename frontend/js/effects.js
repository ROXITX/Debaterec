/* Colour, motion and notification effects. */

import { icons } from "./icons.js";

const root = document.documentElement;

/** #7c5cff -> "124, 92, 255" */
export function hexToRgb(hex) {
  const clean = String(hex || "").replace("#", "").trim();
  const full = clean.length === 3 ? clean.split("").map((c) => c + c).join("") : clean;
  const value = parseInt(full || "7c5cff", 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255].join(", ");
}

/**
 * Repaint the entire interface in a domain's colour.
 * Everything — aurora, buttons, rings, card edges — reads from these two
 * variables, so this one call is the whole theme switch.
 */
export function setAccent(hex, { flash = false } = {}) {
  if (!hex) return;
  const rgb = hexToRgb(hex);
  root.style.setProperty("--accent", hex);
  root.style.setProperty("--accent-rgb", rgb);
  root.style.setProperty("--accent-soft", `rgba(${rgb}, 0.16)`);
  root.style.setProperty("--accent-line", `rgba(${rgb}, 0.42)`);

  if (flash) {
    const aurora = document.getElementById("aurora");
    if (aurora) {
      aurora.classList.remove("aurora--flash");
      void aurora.offsetWidth; // force reflow so the animation can replay
      aurora.classList.add("aurora--flash");
    }
  }
}

const SPARK_COLOURS = ["var(--accent)", "var(--judge)", "var(--supporter)", "var(--critic)"];

/**
 * The colour burst: rings, a radial wash and a scatter of sparks, fired from
 * a point on screen. Self-removing after the longest animation finishes.
 */
export function burst(x, y, { sparks = 22 } = {}) {
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

  const node = document.createElement("div");
  node.className = "burst";
  node.style.left = `${x}px`;
  node.style.top = `${y}px`;

  const wash = document.createElement("div");
  wash.className = "burst__wash";
  node.appendChild(wash);

  for (let i = 0; i < 3; i += 1) {
    const ring = document.createElement("div");
    ring.className = "burst__ring";
    node.appendChild(ring);
  }

  for (let i = 0; i < sparks; i += 1) {
    const spark = document.createElement("div");
    spark.className = "burst__spark";
    const angle = (Math.PI * 2 * i) / sparks + Math.random() * 0.4;
    const distance = 120 + Math.random() * 230;
    spark.style.setProperty("--dx", `${Math.cos(angle) * distance}px`);
    spark.style.setProperty("--dy", `${Math.sin(angle) * distance * 0.62}px`);
    spark.style.setProperty("--spark", SPARK_COLOURS[i % SPARK_COLOURS.length]);
    spark.style.animationDelay = `${Math.random() * 130}ms`;
    node.appendChild(spark);
  }

  document.body.appendChild(node);
  window.setTimeout(() => node.remove(), 1200);
}

/** Fire the burst from the centre of an element. */
export function burstFrom(element, options) {
  if (!element) return;
  const box = element.getBoundingClientRect();
  burst(box.left + box.width / 2, box.top + box.height / 2, options);
}

/* --- toasts --------------------------------------------------------------- */

export function toast(message, { icon = "check", ms = 3200 } = {}) {
  const host = document.getElementById("toasts");
  if (!host) return;
  const node = document.createElement("div");
  node.className = "toast";
  node.innerHTML = `${icons[icon] || icons.check}<span>${escapeHTML(message)}</span>`;
  host.appendChild(node);
  window.setTimeout(() => {
    node.classList.add("toast--exit");
    window.setTimeout(() => node.remove(), 320);
  }, ms);
}

/* --- notices -------------------------------------------------------------- */

export function notice(message, kind = "info") {
  const host = document.getElementById("notices");
  if (!host) return;
  const node = document.createElement("div");
  node.className = `notice${kind === "error" ? " notice--error" : ""}`;
  node.innerHTML = `${kind === "error" ? icons.alert : icons.info}<span>${escapeHTML(message)}</span>`;
  host.appendChild(node);
}

export function clearNotices() {
  const host = document.getElementById("notices");
  if (host) host.innerHTML = "";
}

/* --- helpers -------------------------------------------------------------- */

export function escapeHTML(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function reveal(section) {
  if (!section) return;
  section.classList.remove("hidden");
  section.classList.add("section-enter");
}

/** Count a number up to its target — used for the score rings and metrics. */
export function countTo(element, target, { decimals = 1, ms = 700 } = {}) {
  const start = performance.now();
  const from = Number(element.dataset.value || 0);
  const step = (now) => {
    const progress = Math.min(1, (now - start) / ms);
    const eased = 1 - Math.pow(1 - progress, 3);
    const value = from + (target - from) * eased;
    element.textContent = value.toFixed(decimals);
    if (progress < 1) requestAnimationFrame(step);
    else element.dataset.value = String(target);
  };
  requestAnimationFrame(step);
}
