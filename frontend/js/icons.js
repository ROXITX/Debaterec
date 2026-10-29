/* Inline SVG icons. Kept as strings so the interface ships as plain files with
   no icon-font download and no network dependency at runtime. */

const svg = (paths, extra = "") =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
        stroke-linecap="round" stroke-linejoin="round" ${extra}>${paths}</svg>`;

export const icons = {
  scales: svg(`<path d="M12 3v18M7 21h10M5 7h14M5 7 2 14h6L5 7Zm14 0-3 7h6l-3-7Z"/>`),
  send: svg(`<path d="M4 12h14M13 6l6 6-6 6"/>`),
  film: svg(`<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 4v16M16 4v16M3 9h5M3 15h5M16 9h5M16 15h5"/>`),
  book: svg(`<path d="M4 5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2V5Z"/><path d="M8 3v18"/>`),
  cap: svg(`<path d="m12 4 10 5-10 5L2 9l10-5Z"/><path d="M6 11v5c0 1.5 3 3 6 3s6-1.5 6-3v-5"/>`),
  phone: svg(`<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18.5h2"/>`),
  laptop: svg(`<rect x="3" y="5" width="18" height="11" rx="1.8"/><path d="M2 20h20"/>`),
  car: svg(`<path d="M5 17h14M4 17v-4l2-5h12l2 5v4"/><circle cx="7.5" cy="17.5" r="1.6"/><circle cx="16.5" cy="17.5" r="1.6"/>`),
  bike: svg(`<circle cx="6" cy="17" r="3.2"/><circle cx="18" cy="17" r="3.2"/><path d="m6 17 4-8h5l3 8M9 9h5"/>`),
  shield: svg(`<path d="M12 3 5 6v5c0 4.5 3 8 7 10 4-2 7-5.5 7-10V6l-7-3Z"/>`),
  spark: svg(`<path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M18 6l-2.5 2.5M8.5 15.5 6 18"/>`),
  gavel: svg(`<path d="m14 4 6 6-3 3-6-6 3-3Z"/><path d="m11 7-7 7 3 3 7-7"/><path d="M3 21h9"/>`),
  plus: svg(`<path d="M12 5v14M5 12h14"/>`),
  minus: svg(`<path d="M5 12h14"/>`),
  check: svg(`<path d="m5 12 4.5 4.5L19 7"/>`),
  info: svg(`<circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 8h.01"/>`),
  alert: svg(`<path d="M12 4 2.5 20h19L12 4Z"/><path d="M12 10v4M12 17h.01"/>`),
  up: svg(`<path d="M7 14l5-5 5 5"/>`),
  down: svg(`<path d="M7 10l5 5 5-5"/>`),
  heart: svg(`<path d="M12 20s-7-4.4-7-9a3.9 3.9 0 0 1 7-2.4A3.9 3.9 0 0 1 19 11c0 4.6-7 9-7 9Z"/>`),
  ban: svg(`<circle cx="12" cy="12" r="9"/><path d="m6 6 12 12"/>`),
  list: svg(`<path d="M8 6h13M8 12h13M8 18h13M3.5 6h.01M3.5 12h.01M3.5 18h.01"/>`),
};

export const domainIcon = (key) => icons[key] || icons.spark;
