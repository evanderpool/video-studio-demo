# Video Studio: a short-form editor with a swappable brain

**A local-first pipeline that turns a raw talking-head take into a tight,
captioned, retention-engineered vertical video — where the AI that makes the
editing decisions is a plug-in component, not the system, and every render is
screenshot-verified before it counts as done.**

Built and directed by **Erick Vanderpool** · a portfolio project of Artificial
Management · [public demo (outputs + decision traces) →](https://evanderpool.github.io/video-studio-demo/)

*The production repository is private by design — it holds an operational
security history and competitor research. This case study leads with
architecture, measured results, and the decisions behind them; the public demo
shows real outputs with their full decision traces.*

| 11 days | 66 | 107 | 106/106 | $0 |
|---|---|---|---|---|
| build history, 56 commits | videos produced | finished cuts rendered | passed automated A/V + black-frame QA | recurring cost |

---

## The problem

Short-form product video has one brutal, measured truth: **length and the first
second decide everything.** Before a line of pipeline code, 320 competitor
videos were studied across four creator profiles — and the pattern held. The
strongest account posted a **39-second** median with **22% of videos clearing
100k views**; the weakest posted **48-second** videos and landed **zero hits in
80 tries.** The same product — a portable fan — did **4.8M views as a staged
skit and 422 as a driveway demo: an ~11,000× swing from format alone.**

So the goal was never "use AI to edit video." It was: **turn a raw clip of one
person talking about a product into a 25–40-second vertical cut that wins on
hook, proof, and pace — repeatably, and for $0 in recurring cost.** Local
transcription, local rendering, orchestration under a flat subscription. No
per-video API bill, and nothing about the footage leaving the machine that
filmed it.

## The product

Drop a raw take into a phone-controlled app; get back a finished vertical video
— dead air removed, the strongest take kept, on-screen keyword pops timed to the
words, loudness normalized to broadcast spec, and a QA contact sheet proving it.
The app runs on the desktop and is reachable from a phone over a private VPN, so
the workflow is: film on the phone, send to the PC, review the cut back on the
phone.

The interface is six tabs — Overview, Inventory, Script, Make, Library, Plan —
covering the whole loop from "what should I film this week" through scripting,
editing, QA, and a posting calendar. But the engineering story is one layer
down, in four ideas: **a brain that swaps, a decision contract that every brain
obeys, a compliance backstop that lives in code, and a render that checks its own
work.**

## How a cut is made

Every video runs the same seven stages. The AI only decides *which* moments to
keep and *what* to put on screen — everything around it is deterministic code:

```
  Raw take in  (one person, one product, filmed phone-first)
        │
        ▼
  Transcribe   (local faster-whisper, word-level timestamps — the video
        │       never leaves the machine)
        ▼
  Measure      (ffmpeg silencedetect maps real dead air; ebur128 measures
        │       per-phrase delivery energy; frames sampled + CV-tagged)
        ▼
  Decide  ┌───────────────────────────────────────────────────────┐
        │ │  THE BRAIN SEAM — one JSON contract, three backends:   │
        │ │  local rules · a live Claude session · the API         │
        │ │  picks the beats, their order, the zoom, the pop text  │
        │ └───────────────────────────────────────────────────────┘
        ▼
  Comply       (policy.py strips any on-screen claim TikTok Shop forbids —
        │       enforced in code, after the brain, for every backend)
        ▼
  Render       (ffmpeg: frame-snapped cuts, ±8% corrective grade, HyperFrames
        │       keyword pops, surgical captions, −14 LUFS loudness)
        ▼
  ╔═══════════════════════════════════════════════════════════════╗
  ║  VERIFY — the render checks its own work                       ║
  ║  A/V drift, black frames, freeze, loudness, true-peak, and a   ║
  ║  QA contact sheet; then the brain watches the finished video   ║
  ║  back on a frame grid and approves it or orders ONE recut.     ║
  ╚═══════════════════════════════════════════════════════════════╝
        │
        ▼
  Finished cut  (badged with which brain made it — a degraded fallback can
                 never masquerade as a real edit)
```

> **The editing intelligence is a component behind a contract — not the
> system.** Swap the brain and nothing else changes.

## The brain seam: the idea the whole system is built on

The hard part of building with an LLM is not calling it — it's containing it. In
Video Studio the model lives behind a seam. The pipeline — transcribe, measure,
decide, comply, render, verify — is **identical regardless of which brain
answers.** Only *who* chooses the cuts changes:

| Backend | Who decides | When | Cost |
|---|---|---|---|
| **Local rules** | a deterministic heuristic (silence-split phrases, number+unit and power-word pops) | offline / fallback | free |
| **Live Claude session** | an attended Claude Code session reads the transcript + sampled frames and writes the decision file | desktop, hands-on | flat subscription |
| **API** | the Anthropic API answers unattended, for phone-sent jobs | away from the PC | cents per video |

All three return the **same JSON**: which spans to keep (by source and
timestamp), the grade, up to four keyword pops with their text and timing, a
theme line, and a plain-English note on what was cut and why. That contract is
enforced in one place — `_apply_response` — so **every backend inherits the same
guarantees**: source validation, audio-aware dead-air trimming, cut-padding that
protects the call-to-action, a hard four-pop cap, and pop text snapped to word
boundaries. If a brain returns nothing usable, the system **falls back to the
local rules and labels itself as having done so** — a degraded output can never
pretend to be a real cut.

This is the same architectural move that made a private tool safe to demo
publicly: because the product has no AI *in* it — decisions arrive as a file
through a queue — going from an attended desktop brain to an unattended API brain
**changed no pipeline code.** It was a brain swap, not a rebuild.

### The attended brain, and why it's free

The default production brain is a live Claude Code session with a person at the
keyboard. A small **watcher** program polls a queue; the instant an edit request
lands, it exits and prints the backlog — which re-invokes the session to answer.
That handshake is what makes the $0 cost real: the orchestration runs under a
flat subscription instead of a metered API.

The trade-off was chosen with eyes open, and written down: **a video edit never
silently ships a fallback.** If no session is listening, the job *holds* —
indefinitely — rather than quietly shipping a worse rule-based cut. Scripts,
captions, and research keep a visible 30-minute template fallback, because their
degraded output is obviously a draft; a video's isn't. That distinction —
*which* failures are allowed to degrade silently and which must block — is the
kind of judgment call the whole system is made of.

## Prompting as engineering, not incantation

The prompts in this system are specifications. A few that show the standard:

- **The editing brief refuses to guess.** It hands the model the transcript,
  the silence map, per-phrase energy, and sampled frames, then imposes rules
  the model must obey: hook in the first second; **"the call-to-action is
  sacred"** (never clipped); **end every kept span on a real pause**, because
  cutting mid-phrase clips the last word's sound; the first pop is a hook/pain
  line for muted scrollers, the rest are factual specs; never wall-to-wall
  captions. It closes vision guidance with **"never invent visual facts that
  aren't visible in the frames."**

- **The scriptwriter is a strategist, not a copywriter.** Its prompt says
  *"do not restate the input — out-think it,"* and forces an unprinted strategy
  pass (buyer, pain, top objections, one lead angle) before any words. It bans a
  named list of hollow adjectives — *"amazing, premium, seamless, game-changer —
  each is a hole where a real detail should be"* — and demands sensory
  specificity instead: *"the 6am scramble, the tangled cable nest behind the
  TV."* Length is capped at ~110 words for a 25–40-second read, and *"if you're
  over budget, cut the weakest feature — never the hook, demo, or CTA."*

- **The two prompt voices are kept honest by a metric.** The editing rules exist
  as both an in-session brief and an API system prompt; a `measure_cuts` tool
  scores what fraction of cut-ends actually land on a sentence boundary, so a
  prompt change can be *measured* against real footage instead of eyeballed.

Every one of those constraints is a decision about what "good" means for this
medium, encoded so the model can't drift from it.

## Multimodal: the brain looks at the footage

A transcript can't tell you whether the product is on screen when it's named, or
which of two takes is sharper. So the pipeline samples frames from every clip —
about one every four seconds for talking clips — labels each with the words being
said at that moment, and runs cheap computer-vision tags on them: sharpness
(variance-of-Laplacian), face detection and centering. The brain uses them to
six documented ends — verify the product is visible when named, protect the
proof-demo moment, prefer the sharper re-take, pick a scroll-stopping first
frame, and keep a pop from landing over a centered face. On the API path the
frames are base64 image blocks, thinned to a cost ceiling; on the attended path
the session reads the JPEGs off disk. And the rule when a CV tag and the actual
picture disagree: **believe the frame.**

## Compliance is a code backstop, not a polite request

TikTok Shop moderation weighs **on-screen text more heavily than the spoken
voice** — a risky claim flashed on screen can high-risk-classify a video even
when the sentence is qualified, and six strikes in 90 days freezes commissions.
So compliance isn't left to the prompt. `policy.py` is a hard filter that runs
**after** the brain, on **every** backend, screening pops and captions against
five categories — pricing, superlatives, health claims, brand comparisons, and
false urgency — with the policy decisions written into the module:

- price, health, and brand-comparison claims are **blocked everywhere**;
- superlatives and urgency are **blocked on screen but allowed in the spoken
  script**;
- "limited edition" is **always allowed** — it's a genuine product attribute;
- **urgency must be true** — a real seasonal deadline or genuine scarcity, never
  a manufactured one.

The precision is in the details: a bare percentage passes ("HEPA 99.97%") while
"50% off" is caught; a pet product's "TREATS" survives while "treatment" is
blocked; a pop naming the video's *own* brand survives while "BETTER THAN
[rival]" drops. The prompts are the first line of defense so the risky text is
never authored; `policy.py` is the backstop that assumes the prompt will
sometimes fail — because on a live run, it did, and the filter was tightened the
same day.

## Measured, not claimed

The pipeline logs quantifiable results for every render — durations, QA verdicts,
which brain decided — and this is the first time they're rolled up. Across the 66
videos and 107 finished cuts on disk:

| What | Result | How it's known |
|---|---|---|
| A/V sync passed | **106 / 106** cuts | `\|video − audio\|` duration checked per render |
| No black frames | **106 / 106** cuts | ffmpeg `blackdetect` per render |
| Median A/V drift | **0.06 s** (worst 0.15 s) | measured on the finished file |
| Landed in the 18–50 s target | **101 / 106** | duration is the #1 failure predictor, so a 90 s render can't pass QA silently |
| Median compression | **86 s raw → 30 s cut** (kept ratio 0.32) | ~two-thirds of every take is dead air or weaker takes, removed |
| Self-review outcome | **47 approve, 2 recut** | the brain watched each finished cut back and ordered a recut when it saw a flaw |

Those sync and black-frame numbers are the payoff of an A/V chain built
deliberately: variable framerate converted to constant before scaling,
frame-snapped cut boundaries, audio padded to the exact snapped length, and a
**concat filter with a single re-encode** rather than the naive concat demuxer —
because the demuxer accumulates AAC priming delay into visible drift. The
rationale is written into the code, not just the result.

### The render checks its own work

"Verified" here is mechanical. After every cut, one ffmpeg pass measures A/V
drift, black frames, frozen frames, loudness, and true-peak, and renders a
contact sheet plus a frame at each keyword pop. Then the attended brain does
something most pipelines don't: it **watches the finished video back** — as a
one-frame-per-second grid — and answers six viewer questions (does the first
second stop the scroll? any jarring jump-cuts? are the pops on the right frames
and not over a face? is the proof-demo intact? does the CTA get clipped?). The
verdict is *approve* or *recut*, exactly one recut allowed, then it ships —
labeled *unreviewed* if the session times out, never silently. Of 49 reviewed
cuts, it approved 47 and caught 2 worth redoing.

## Directed across the stack — not just delegated

The AI wrote code and made per-video cuts. The architecture, the trade-offs, and
the standards were decisions I owned and can defend — and that breadth is the
real evidence of understanding the system, not just steering it. Each of these
is written down in the project's engineering log:

- **Architecture.** The brain seam — a JSON contract with three interchangeable
  backends and one central validator — was the founding decision. It's why the
  system is free by default, why it went from private to publicly demoable
  without a rewrite, and why a bad model response can never ship as a real cut.
- **Cost.** $0 recurring was a *designed* constraint, not a corner cut: local
  faster-whisper replaced a paid speech API (kept schema-compatible so it was a
  true drop-in), local ffmpeg does the rendering, and the orchestration runs
  under a flat subscription. The accepted cost — "the PC must be on, and a
  session must be listening" — was weighed and documented, not stumbled into.
- **Editing judgment.** Every rule the brain obeys came from the 320-video
  study, encoded as code: the ≤45-second target enforced in QA, the mandatory
  proof-demo, surgical captions over wall-to-wall (the losing pattern),
  bounded ±8% corrective grade so a video looks clean without looking graded.
- **Security.** I ran two formal multi-persona reviews — six specialists, then
  four — that attacked the work and produced ranked punch-lists. When a live app
  key leaked into a log via a query string, I didn't just rotate it; I removed
  query-string auth entirely (header + HttpOnly cookie only), scoped the
  firewall rule to the VPN's address range, and verified the fix with a route
  smoke test. The public-demo decision — accept strangers' video, or don't — I
  resolved on the privacy side and scrapped the upload path deliberately.
- **Honesty as a discipline.** Every cut is badged with the brain that made it.
  QA warns loudly rather than passing silently. A held video waits rather than
  shipping a worse one. When the reviews found real problems — captions that
  had never actually rendered, a metronomic zoom, analytics that summed the
  wrong channel — they're recorded as findings, not hidden.

## The decisions that shaped it

A system like this is a pile of defended choices. A few that show the standard:

- **Rank by what the pipeline controls.** The affiliate export showed most
  commission came from live selling and ads — channels this tool doesn't touch.
  The analytics were rebuilt to split by content type and rank products by their
  *video-attributed* number, so the tool recommends what filming can actually
  move, not what some other channel already sold.
- **Urgency has to be real.** The multi-variant editor produces value / demo /
  scarcity cuts from one take — but each has a viability gate, and the scarcity
  cut sets itself *invalid* rather than manufacture a fake deadline. A
  feature-list with no demo is likewise refused, because the study proved it's
  the zero-hit pattern.
- **Cache the expensive thing.** Keyword pops are HTML rendered to transparent
  video through a headless browser — slow. They're content-hashed and cached, so
  identical pops across a video's three style variants and its regenerates never
  re-launch the browser, and editing the template invalidates the cache.
- **Restore points as a habit.** 20 git tags mark "before I changed X," paired
  with local snapshots — so an experiment that goes wrong costs minutes, not the
  build.
- **Real bugs, in someone else's code.** Adapting a third-party editing library
  to Windows surfaced ~6 genuine defects — a UTF-8 stdout crash, subtitle-path
  backslashes, a broken auto-grade metadata path, dropped video alpha — each
  found, fixed, and documented rather than worked around.

## Honest about what's unfinished

The same reviews that praised the substance found real gaps, and they're kept in
the open: burned-in captions were built but a one-flag bug meant they hadn't
actually rendered in app-made videos (caught in review, fix staged); the zoom is
mechanical where it should be beat-driven; there are no automated tests yet on
the pure core, and the review names exactly which functions should get the first
fifteen; and the biggest structural item — linking each finished video back to
its script and product so a performance-learning loop can close — is scoped and
waiting. A portfolio piece that hides its backlog isn't credible; this one names
it.

## What it demonstrates

- **LLM systems design** — a model contained behind a swappable contract with a
  central validator, three interchangeable backends, and graceful, *labeled*
  degradation.
- **Prompt engineering** — editing, strategist-scriptwriting, SEO, and
  self-review prompts that encode hard constraints and a measured feedback loop,
  not vibes.
- **Multimodal reasoning** — transcript plus CV-tagged frames driving concrete
  editing decisions, cost-bounded on the API path.
- **Media engineering** — a frame-accurate ffmpeg A/V chain (106/106 clean),
  loudness normalization, corrective grading, and browser-rendered motion
  graphics.
- **Security & compliance** — VPN-gated auth, adversarial self-review, a code-
  enforced platform-policy filter, and a deliberate private/public boundary.
- **Constraint-driven judgment** — a genuinely useful daily tool built to a hard
  $0-recurring, local-first, single-operator constraint, with every trade-off
  written down.

---

**Erick Vanderpool** — data analyst and AI engineer.
[github.com/evanderpool](https://github.com/evanderpool) · Video Studio is a
portfolio project of Artificial Management. The production system is private;
the [public demo](https://evanderpool.github.io/video-studio-demo/) shows real
outputs with their full decision traces.
