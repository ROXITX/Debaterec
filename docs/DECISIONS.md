# Design decisions

A record of the choices that shaped this implementation, why they were made, and
what the alternative was. Useful when writing up the project, and useful for
anyone changing the code later.

---

## 1. Preferences are typed constraints over named facets

**Decision.** A preference is a `NumericConstraint` or a `CategoricalConstraint`
over a facet name, not a domain-specific field.

**Why.** "Under two hours" (movies), "under 40k" (phones), "under three months"
(courses) and "above 40 kmpl" (bikes) are the same operation on different
facets. Modelling them identically is what lets one retrieval engine, one debate
engine and one judge serve seven domains without a single `if domain ==` in the
core.

**Alternative rejected.** Per-domain preference classes with per-domain scoring.
Simpler to write for domain one, and it makes domain eight a rewrite.

---

## 2. Constraints are checked in code before any model sees the candidate

**Decision.** `recommender/filters.py` produces a pass / fail / unknown audit for
every constraint. The agents receive it as ground truth. The Judge prompt says
explicitly to discard any argument that contradicts it.

**Why.** The known failure mode of LLM-as-a-judge is that a fluent argument beats
a correct one. Removing the facts from the model's discretion removes that
failure mode for anything checkable. It also means the constraint-violation rate
is a hard number the evaluation can report rather than an LLM's self-assessment.

**Cost.** The agents cannot reason about anything the audit does not cover. That
is the intended trade.

---

## 3. Satisfaction is graded, and the grade is scaled by the catalogue

**Decision.** Missing a soft constraint decays continuously rather than failing
outright, and the decay is normalised by the **spread of that facet across the
real catalogue**, not by the constraint value.

**Why.** Normalising by the constraint value produced an obvious bug: against
"after 2015", a 1984 film scored 97% satisfied, because 31 is small next to 2015.
Against the actual year spread (1937–2024) it correctly scores as a bad miss,
while a 2014 film stays a trivial one. The same fix makes "5-star safety" behave
sensibly on a 2–5 scale.

**Where it lives.** `domain_stats()` in `domains/registry.py` computes the
percentiles; `NumericConstraint.scale` carries them.

---

## 4. Vague words resolve against the catalogue, not against constants

**Decision.** "Cheap", "big battery", "lightweight" become constraints at the
35th or 65th percentile of that facet **as it actually exists in the data**.

**Why.** A hard-coded threshold is wrong the moment the catalogue changes. The
first version used the facet's declared typical range and turned "best camera"
into "at least 134 MP", which excluded almost everything. Percentiles fixed it
without any hand-tuning.

---

## 5. Hardness is judged per clause, not per sentence

**Decision.** Whether a constraint is hard is decided from the clause the number
sits in, not from whether the sentence contains the word "must".

**Why.** "Phone under 30k with a big battery, **must** be under 200g" was turning
every preference in the sentence into a hard filter, which collapsed the result
set to nothing. Splitting on clause boundaries fixed it. There is a regression
test for this.

---

## 6. Comparison cues bind only within a short radius

**Decision.** A cue like "under" governs a number only if it sits within 8
characters of it. Otherwise the facet's own direction decides.

**Why.** In "under 15 lakh with 5 star safety", the "under" was reaching across
and turning "5 star safety" into *at most* 5 stars. Distance-limiting the cue,
and defaulting to the facet's natural direction (`better: higher` → at least),
fixed it and improved several other queries as a side effect.

---

## 7. Hybrid alpha slides with query specificity

**Decision.** `alpha` (the weight on text similarity vs. metadata matching)
starts at 0.70 and decreases as the query accumulates constraint weight, floored
at 0.42.

**Why.** A vague request has nothing to check, so similarity should carry it. A
precise one states most of what matters in structured form — and leaning on text
similarity there is exactly how a 25-lakh diesel SUV ended up in a list that had
explicitly excluded both. The endpoints are hyperparameters;
`experiments.py --sweep-alpha` tunes them.

---

## 8. The scoring weights were changed from the PRD's starting point

**Decision.** 0.28 retrieval / 0.22 supporter / 0.15 evidence / 0.20 constraint /
0.15 preference, replacing the PRD's 0.35 / 0.25 / 0.20 / 0.10 / 0.10.

**Why.** Measured. The original weighting scored items that *read* well but
missed a stated preference as "recommend". Raising the constraint and preference
weights, and adding a rule that a notable miss caps the verdict at "consider",
matched the ranking to what the explanations were actually saying.

**Status.** Still hyperparameters. The PRD is right that they should be swept
rather than asserted.

---

## 9. Rounds run in phases across candidates, not candidate by candidate

**Decision.** All Supporters run concurrently, then all Critics, then all Judges.

**Why.** Two reasons, one technical and one about the interface. Technically it
lets every call in a round go out at once, bounded by a semaphore. For the
interface it means the arena shows an honest progression — the Supporters really
are all arguing before any Critic responds — instead of a scrambled order that
would misrepresent the protocol.

**Cost.** A barrier between rounds. Acceptable, because the Critic is supposed to
see the Supporter's case (PRD §18 round 2), so the dependency is real.

---

## 10. Dataset text is untrusted input

**Decision.** Item descriptions are fenced with a distinctive delimiter,
instruction-like phrases are replaced with a visible `[redacted]` marker, and the
agents are told the block is data.

**Why.** A recommendation catalogue is third-party content. Text is *marked*
rather than silently deleted so that an attempt shows up in the Critic's
`unsupported_claims` instead of vanishing.

---

## 11. There is a deterministic fallback for every agent

**Decision.** Each agent has a `heuristic()` that reasons from the constraint
audit. It runs when no LLM is configured, when the provider fails, and when a
reply cannot be parsed after one retry.

**Why.** Three benefits for one mechanism: the application is usable before the
user has an API key; the test suite is reproducible; and the no-LLM condition of
the ablation study is the same code path rather than a separate implementation
that could drift.

**Caveat.** In deterministic mode conditions E2, E3 and E4 collapse to the same
agents and produce identical numbers. This is stated in the README so the
identical rows are not read as a bug.

---

## 12. Lexical retrieval by default, dense as a flag

**Decision.** BM25 (implemented in NumPy) + TF-IDF with word and character
n-grams. `sentence-transformers` is an optional install behind
`RETRIEVAL_MODE=semantic`.

**Why.** Zero download, instant startup, identical behaviour on a fresh Windows
or macOS machine. The character n-grams matter for this catalogue specifically:
they are what let "sci-fi" find "science fiction" and "macbook" find "MacBook
Air". BM25 was written out rather than imported so the ranking function is
inspectable and there is one fewer dependency.

---

## 13. Server-Sent Events, not WebSockets

**Decision.** The pipeline is an async generator; the HTTP layer forwards its
events over SSE.

**Why.** The traffic is one-directional, SSE reconnects on its own, and it needs
no extra dependency on either side. A queue rather than a buffered list is what
makes it genuinely live — the browser sees "Critic is examining Pixel 8a" while
that call is still in flight.

---

## 14. Multi-file frontend with no build step

**Decision.** Plain ES modules and plain CSS, served directly by FastAPI.

**Why.** One command starts the whole system on Windows and macOS alike. No Node,
no npm, no build failures on a machine that has a different toolchain. The colour
system is two CSS variables, so a domain switch repaints the entire interface
without touching a component.

---

## 15. The evaluation labels are hand-assigned, not derived

**Decision.** Relevance grades in `data/evaluation/queries.json` were assigned by
reading the catalogue records before running any system, and deliberately not
generated by the constraint checker.

**Why.** Deriving them from the checker would score the constraint-based methods
against their own output. Every number would be circular and none of them would
mean anything.

---

## 16. The model ID is discovered, never trusted

**Decision.** `setup_key.py` and the startup check ask the Gemini API which
models the key can use and pick one. A 404 mid-request triggers rediscovery and
a retry.

**Why.** Model IDs are retired over time. Combined with a fallback-on-error
design, a stale ID produces the worst possible outcome: the system keeps working,
the interface still says "gemini", and every argument is silently rule-written.
Discovery plus a startup verification plus a `degraded` flag on the response
means the system cannot claim a capability it does not have.

**Cost.** One extra API call at startup.

---

## 17. Catalogue filler is generated, and labelled as generated

**Decision.** 214 curated records are copied verbatim from `data/seed/`;
`data/build_catalogue.py` generates 11,200 more. Generated records carry
`"synthetic": true`, are badged in the interface, and can be switched off.

**Why.** A 214-item catalogue cannot demonstrate anything about retrieval at
scale — BM25 IDF is meaningless, latency is unmeasurable, coverage is trivially
100%. Real datasets were not reachable from the build environment, so the choice
was between a small honest catalogue and a large labelled-as-synthetic one. The
label is what makes the second option acceptable.

**Two constraints on the generator.** Synthetic films and books get invented
directors and authors, because attributing a nonexistent film to a real director
fabricates a claim about a real person. Synthetic products get invented brands,
because inventing specifications and prices under a real manufacturer's name
fabricates product information about a real company.

**Cost.** Generated titles read as generated. That is the correct trade — the
alternative is plausible-looking fabrication.

---

## 18. Evaluation runs against the curated pool

**Decision.** `experiments.py` filters to non-synthetic records by default.

**Why.** The labelled query set only covers curated records. Against the full
catalogue, a generated item in the top 5 scores as a miss regardless of whether
it was a good recommendation, so every metric drops for a reason that has nothing
to do with ranking. `--full-catalogue` exists for latency measurement and prints
a warning that its relevance numbers are not comparable.

---

## 19. Two scaling fixes the larger catalogue forced

**Sparse BM25.** The term-document matrix was dense. At 2,400 items that is
roughly 180MB for one domain, multiplied by every domain loaded. Rewritten on
`scipy.sparse` in CSC layout, since scoring slices by column — one column per
query term.

**Character n-grams narrowed to titles and tags.** They were running over full
prose descriptions. Their only job is fuzzy surface matching — letting "sci-fi"
reach "science fiction" and "macbook" reach "MacBook Air" — and prose adds cost
without recall. Restricting them took index construction on the movie catalogue
from **11.4s to 1.15s**.

**Indexes build lazily.** Building all seven at startup costs far more than
loading them, and a session typically touches two or three domains.

---

## 20. Requests are paced, not just retried

**Decision.** A token-bucket throttle (`GEMINI_RPM`, default 10) sits in front of
the Gemini client, and 429 responses are retried using the `retryDelay` Google
returns rather than a guessed backoff.

**Why.** One debate over eight candidates is 25 calls dispatched in bursts of
six. A free-tier key allows roughly ten a minute. Without pacing, the very first
search exhausts the minute and everything after it fails — and retrying a 429 has
already spent the wall-clock time, so pacing strictly dominates retrying.

`setup_key.py` also drops `CANDIDATES_DEBATE` to 5 when it configures a key,
because 25 calls at 10 rpm is two and a half minutes of waiting for one search.

---

## 21. A bug this analysis exposed: E2 was not an ablation

**Found.** Sizing the LLM budget meant counting calls per condition, which
surfaced that `supporter_only` skipped the Critic but still ran the **LLM
Judge**. Condition E2 was therefore "retrieval + Supporter + Judge" while the
report labelled it "retrieval + Supporter".

**Why it mattered.** The isolated contribution of the Supporter was never
measured, and E2-vs-E3 understated the Critic's effect because both conditions
already had a judge.

**Fixed.** `supporter_only` now uses the deterministic judge, like `no_judge`.

**Worth noting for the write-up:** this was invisible in deterministic mode,
where all three conditions collapse to identical rule-based agents and produce
identical numbers. An ablation that cannot distinguish its own conditions cannot
reveal a bug in how they are defined.

---

## Open questions worth investigating

- Does the debate still help once a strong LLM is attached, or does the
  deterministic audit already capture most of the gain? The ablation is built to
  answer this; it needs an API key and a run.
- Is the phase barrier between rounds costing meaningful latency at larger
  `CANDIDATES_DEBATE` values?
- Would a per-domain alpha beat the single sliding one?
- The rebuttal round is implemented but off by default. Does it change rankings,
  or only the wording of explanations?
