import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

NAVY, BLUE, CYAN, GREEN, RED, AMBER = "#1F3864", "#2563EB", "#0891B2", "#15803D", "#B91C1C", "#B45309"
GREY, DARK = "#F2F4F7", "#1F2937"
WIDTH_IN, UNITS = 7.0, 100.0
K = WIDTH_IN / UNITS                      # inches per data unit (equal aspect)

items = []                                 # (kind, payload) laid out top-down
cur = [0.0]                                # running cursor (distance from top, in data units)
boxes, arrows, texts = [], [], []


def place(h):
    top = cur[0]
    cur[0] += h
    return top, top + h


def gap(g):
    cur[0] += g


def box(cx, w, h, text, fc=GREY, ec=NAVY, tc=DARK, fs=8.8, bold=False):
    top, bot = place(h)
    boxes.append((cx, (top + bot) / 2, w, h, text, fc, ec, tc, fs, bold))
    return top, bot


def row(specs, h):
    top, bot = place(h)
    for cx, w, text, fc, ec, tc, bold in specs:
        boxes.append((cx, (top + bot) / 2, w, h, text, fc, ec, tc, 8.8, bold))
    return top, bot


def varrow(x, y1, y2):
    arrows.append(((x, y1), (x, y2), NAVY))


def label(x, text, fs=10.4, color=BLUE, bold=True, ha="left", italic=False):
    top, _ = place(3.4)
    texts.append((x, top + 1.7, text, fs, color, bold, ha, italic))


# ------------------------------------------------------------------ layout
texts.append((50, 1.6, "DebateRec — NLP + Multi-Agent Debate System Architecture", 12.5, NAVY, True, "center", False))
texts.append((50, 5.0, "natural-language query → structured preferences → hybrid retrieval → adversarial LLM debate → explainable ranking",
              7.4, "#555555", False, "center", True))
cur[0] = 8.0
t, b = box(50, 62, 6.5, "USER — free-text natural-language query\ne.g. “a lightweight laptop under ₹70k for a first-time coder”",
           fc=NAVY, tc="white", bold=True)
gap(3.2)
varrow(50, b + 0.2, cur[0] - 0.2)

label(1.5, "1 · NLP LAYER   (app/nlp/)")
t, b_nlp = row([(17.5, 31, "Domain Router\nrule-weighted token/phrase\nscoring + LLM fallback\n(intent classification)", GREY, BLUE, DARK, False),
                (50, 31, "Rule-based Parser\nregex + unit lexicon\nhard/soft · negation ·\ncomparison direction", GREY, BLUE, DARK, False),
                (82.5, 31, "LLM Preference Extractor\nstructured JSON (Pydantic)\nimplicit / compositional\npreferences · ambiguities", GREY, BLUE, DARK, False)], 11)
gap(3.6)
varrow(50, b_nlp + 0.2, cur[0] - 0.2)
t, b = box(50, 92, 8.5, "MERGE POLICY: rules are authoritative per facet (cannot hallucinate a number);\nthe LLM may only ADD facets the rules missed, or promote soft → hard.\nResult: a structured QuerySpec", ec=BLUE, fs=8.4)
gap(3.4)
varrow(50, b + 0.2, cur[0] - 0.2)

label(1.5, "2 · HYBRID RETRIEVAL   (app/recommender/)")
t, b_r = row([(13.5, 24, "BM25\n(Okapi, k1=1.4, b=0.72)\nsparse term match", GREY, CYAN, DARK, False),
              (38.5, 24, "TF-IDF word\n(1–2-gram cosine)\nparaphrase recall", GREY, CYAN, DARK, False),
              (63.5, 24, "TF-IDF char\n(3–5-gram, titles/tags)\nfuzzy surface match", GREY, CYAN, DARK, False),
              (88, 22, "Dense embeddings\n(optional,\nsentence-transformers)", GREY, CYAN, DARK, False)], 9.5)
gap(1.8)
top, _ = place(5.0)
texts.append((50, top + 1.2, "fused score = 0.45·BM25 + 0.35·TF-IDF(word) + 0.20·TF-IDF(char)", 8.2, "#444444", False, "center", True))
texts.append((50, top + 3.7, "lexical mode (default); embeddings swap in unchanged", 8.2, "#444444", False, "center", True))
gap(0.6)
t, b = box(50, 92, 8.5, "Constraint filtering + result diversification → shortlist of CANDIDATES_DEBATE items\n(deterministic per-facet PASS / FAIL / UNKNOWN audit computed in code,\nnot by the LLM)", ec=CYAN, fs=8.4)
gap(3.4)
varrow(50, b + 0.2, cur[0] - 0.2)

label(1.5, "3 · MULTI-AGENT DEBATE ENGINE   (app/agents/)")
t, b_d = row([(16, 29, "ROUND 1\nSUPPORTER\nargues FOR\n(structured LLM output)", "#ECFDF5", GREEN, DARK, False),
              (50, 29, "ROUND 2\nCRITIC\nargues AGAINST\n(sees the Supporter's case)", "#FEF2F2", RED, DARK, False),
              (84, 29, "ROUND 3 (optional)\nREBUTTAL\nSupporter concedes\nor rebuts", "#FFF7ED", AMBER, DARK, False)], 11)
arrows.append(((31, (t + b_d) / 2), (35.2, (t + b_d) / 2), "#888888"))
arrows.append(((65, (t + b_d) / 2), (69.2, (t + b_d) / 2), "#888888"))
gap(3.6)
varrow(50, b_d + 0.2, cur[0] - 0.2)
t, b_j = box(50, 76, 13, "ROUND 4 — JUDGE\nreconciles the Supporter and Critic arguments against the\nDETERMINISTIC CONSTRAINT AUDIT (treated as ground truth);\ndiscards any claim that contradicts it\n⇒ final_score · decision · confidence",
             fc=NAVY, tc="white", bold=True, fs=8.4)
gap(3.4)
varrow(50, b_j + 0.2, cur[0] - 0.2)

label(1.5, "4 · RANKING & EXPLANATION")
t, b = box(50, 92, 8.5, "Ranked, explainable results: pros, cons, explicit trade-offs,\nfull debate transcript, streamed live over FastAPI + Server-Sent Events", ec=NAVY, fs=8.6)
gap(2.2)
top, _ = place(3.6)
texts.append((50, top + 1.4, "The backend below drives the LLM Preference Extractor and, in LLM mode, the Supporter / Critic / Judge agents.", 7.6, "#444444", False, "center", True))
t, b = box(50, 92, 11, "PLUGGABLE LLM BACKEND   (app/llm/, selected at runtime via a factory)\nGemini (cloud, auto-discovered model)\nOllama (local / offline, e.g. llama3.1:8b)\nMock (deterministic, zero-dependency fallback)",
           fc="#EFF6FF", ec=BLUE, fs=8.4)
total = cur[0] + 1.5

# ------------------------------------------------------------------ draw
fig = plt.figure(figsize=(WIDTH_IN, total * K), dpi=240)
ax = fig.add_axes([0, 0, 1, 1])
ax.set_xlim(0, UNITS)
ax.set_ylim(total, 0)                       # y grows downward
ax.axis("off")
for cx, cy, w, h, text, fc, ec, tc, fs, bold in boxes:
    ax.add_patch(FancyBboxPatch((cx - w / 2, cy - h / 2), w, h, boxstyle="round,pad=0.2,rounding_size=1.6",
                                linewidth=1.3, edgecolor=ec, facecolor=fc, zorder=3))
    ax.text(cx, cy, text, ha="center", va="center", fontsize=fs, color=tc, weight="bold" if bold else "normal",
            zorder=4, linespacing=1.35)
for (x1, y1), (x2, y2), col in arrows:
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle="-|>", mutation_scale=10, linewidth=1.4, color=col, zorder=2))
for x, y, text, fs, color, bold, ha, italic in texts:
    ax.text(x, y, text, ha=ha, va="center", fontsize=fs, color=color, weight="bold" if bold else "normal",
            style="italic" if italic else "normal")
fig.savefig("architecture_new.png", facecolor="white")
print("saved", total)
