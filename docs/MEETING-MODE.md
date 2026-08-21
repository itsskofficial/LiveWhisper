# Meeting Mode — Specification

Status: draft · Target: LiveWhisper 0.2 · Last updated: 2026-08-21

---

## 1. Summary

LiveWhisper has two modes.

**Dictation mode** (shipped, v0.1). Press a hotkey, capture system audio + mic,
transcribe, prepend a prompt profile, paste at the cursor.

**Meeting mode** (this spec). Turn it on for the duration of a call. It transcribes
both channels continuously, watches the other participants' speech for questions that
genuinely need outside information, and lines those up in a queue. You click one and
it decides for itself what to consult — local documents, an MCP server, the web — and
returns an answer. Several can run at once.

The distinguishing bet: every competitor answers from a snapshot you uploaded, and
hands the answer to a walled overlay. Meeting mode queries live systems and can drop
the answer wherever your cursor is.

### Goals

- Surface only questions worth answering, with high precision
- Answer them from live sources: RAG over your documents, MCP tools, web search
- Run several answers concurrently without blocking the meeting or each other
- Work with local models via Ollama, or any cloud provider you configure
- Produce a meeting summary from both channels when the meeting ends

### Non-goals for 0.2

- Speaker diarization beyond the two channels (you vs. them)
- Auto-answering without a click
- Writing to external systems without confirmation
- Mobile, web, or non-Windows platforms
- Real-time translation

### Operating assumption, and its risk

The user has stated that meeting participants know the tool is in use and will wait
for an answer. This relaxes the latency budget substantially and removes any need for
concealment.

**It should not be architected as a hard dependency.** In large calls, client calls, or
standups, nobody will pause. Every answer must therefore arrive asynchronously into the
queue and remain useful two minutes later. Treat "the meeting waits" as a best case that
improves the experience, never as a precondition for it working.

---

## 2. Architecture

```
                    ┌──────────────────────────────────────┐
  system audio ────▶│  capture (existing, channels split)  │
  microphone   ────▶└──────────────────┬───────────────────┘
                                       │
                        ┌──────────────┴──────────────┐
                        ▼                             ▼
              ┌──────────────────┐          ┌──────────────────┐
              │  live draft ASR  │          │  final ASR pass  │
              │  (low latency)   │          │  (large-v3)      │
              └────────┬─────────┘          └────────┬─────────┘
                       │                             │
                       ▼                             ▼
              ┌──────────────────┐          ┌──────────────────┐
              │ question detector│          │    transcript    │
              │ (small local LLM)│          │      store       │
              └────────┬─────────┘          └────────┬─────────┘
                       │                             │
                       ▼                             ▼
              ┌──────────────────┐          ┌──────────────────┐
              │  question queue  │          │ meeting summary  │
              │  (state machine) │          │   (on end)       │
              └────────┬─────────┘          └──────────────────┘
                       │ click
                       ▼
              ┌──────────────────────────────────────────┐
              │  answer pipeline: route → execute → say   │
              │  ┌────────┐  ┌────────┐  ┌────────────┐  │
              │  │  RAG   │  │  MCP   │  │ web search │  │
              │  └────────┘  └────────┘  └────────────┘  │
              └────────────────────┬─────────────────────┘
                                   ▼
                    overlay panel  ·  paste at cursor
```

### Module layout

```
livewhisper/
  audio.py            existing — MODIFIED: stop mixing, expose channels separately
  transcribe.py       existing — MODIFIED: add streaming draft tier
  meeting/
    __init__.py
    session.py        meeting lifecycle, owns the other components
    stream.py         rolling transcript buffer, per channel
    detect.py         question detection over the system channel
    queue.py          question state machine
    answer.py         router + executor + synthesiser
    summary.py        end-of-meeting summary
  context/
    packs.py          context pack definitions and loading
    ingest.py         file/URL/folder → chunks
    store.py          sqlite + sqlite-vec
    retrieve.py       embedding search
  providers/
    base.py           chat(), embed(), stream() interfaces
    ollama.py
    openai.py         also serves any OpenAI-compatible endpoint
    anthropic.py
    groq.py
  mcp/
    client.py         MCP client — connect, discover tools, call
    server.py         LiveWhisper AS an MCP server
  ui/
    panel.py          meeting panel (extends the existing overlay)
    queue_view.py
```

---

## 3. Audio and transcription

### 3.1 Channel separation

`audio.py` currently sums system and mic into one mono track. **Meeting mode requires
them kept apart.** This is the single highest-value change in the spec and costs
nothing: it yields speaker attribution with no diarization model, no added latency, and
no accuracy penalty.

`Recorder.stop()` keeps returning the mixed track for dictation mode. Add a parallel
path that exposes both channels:

```python
@dataclass
class DualRecording:
    system: np.ndarray      # mono float32 @ 16 kHz — what they said
    mic: np.ndarray         # mono float32 @ 16 kHz — what you said
    seconds: float
    system_peak: float
    mic_peak: float
```

Clock drift between the two devices is ~0.1% (roughly 2s over 30 minutes). For
attribution this is irrelevant. For summary timestamps, anchor both to wall-clock at
callback time rather than to sample counts.

### 3.2 Two-tier transcription

| Tier | Purpose | Latency | Model |
| --- | --- | --- | --- |
| Draft | Live view, feeds the detector | < 2 s behind speech | streaming model |
| Final | Transcript of record, summary | end of meeting | `large-v3` |

The draft only has to be good enough to detect questions and retrieve against. Errors
in the draft do not reach the transcript of record.

**Model choice for the draft tier is language-dependent and must stay configurable.**
Parakeet TDT 0.6B v3 is the strongest streaming option — 6.34% WER, beats `large-v3`,
a quarter the size, and a transducer architecture that streams natively rather than
faking it with chunks. **But it covers 25 European languages and does not include
Hindi.** Given the measured Hinglish behaviour in `README.md`, Parakeet cannot be the
only draft engine.

```yaml
draft:
  engine: auto        # auto | parakeet | whisper-turbo | none
  # auto: parakeet when transcription.local.language is European or English,
  #       whisper-turbo otherwise
```

With `whisper-turbo`, run chunked with Silero VAD: cut on >600 ms silence rather than a
fixed timer, so chunks land on utterance boundaries.

If the draft tier is unavailable, meeting mode still records and still produces a
summary — the queue is simply disabled and says so.

### 3.3 Rolling transcript buffer

`stream.py` maintains per-channel utterance lists:

```python
@dataclass
class Utterance:
    channel: Literal["system", "mic"]
    text: str
    t_start: float          # seconds from meeting start
    t_end: float
    confidence: float
    is_final: bool          # false while the draft may still revise it
```

The detector reads a window of the last `detect.window_seconds` (default 90) from the
**system channel only**.

---

## 4. Question detection

This is where the product succeeds or fails. A queue full of junk is worse than no
queue, because the user stops reading it and every downstream feature dies with it.

### 4.1 Why this is hard

Rhetorical and genuine questions are **syntactically identical**; the distinction lives
in prosody, which the transcript discards. Published classifiers reach ~0.76 F1 on the
rhetorical class and ~67% overall accuracy. Modern instruction-tuned models do better
with conversational context, but the ambiguity is real and no prompt eliminates it.

Meetings are also full of question-shaped noise that must never be queued:

- Audio and logistics checks — *"can you hear me?"*, *"are you seeing my screen?"*
- Discourse markers — *"does that make sense?"*, *"right?"*, *"you know?"*
- Rhetorical framing — *"and why does that matter? Well, because…"*
- Questions the speaker answers themselves seconds later
- Questions clearly directed at another named participant
- Social and procedural — *"should we move on?"*, *"how was your weekend?"*

### 4.2 The test the detector applies

Not *"is this a question?"* but:

> **Does answering this require information that is not already available in this
> conversation, and that the user would otherwise have to go look up?**

This single reframing removes most false positives. A question whose answer is about to
be spoken by someone in the room fails the test.

### 4.3 Implementation

Runs every `detect.interval_seconds` (default 4) on the rolling system-channel window.

- **Model**: small instruct model, local by default. `qwen2.5:3b-instruct` or
  `llama3.2:3b` via Ollama. Configurable per §7; a cloud model may be used but the
  detector runs constantly, so a local model is the sane default for cost.
- **Input**: the window with speaker labels, plus the list of currently-queued
  questions so it can avoid re-emitting them.
- **Output**: strict JSON, schema-validated, retried once on parse failure.

```json
{
  "questions": [
    {
      "verbatim": "so what's the current status on the vendor migration?",
      "normalized": "What is the current status of the vendor migration?",
      "needs_external_info": true,
      "answerable_from": ["documents", "mcp", "web"],
      "confidence": 0.82,
      "t_asked": 412.5,
      "reason": "asks for project state not mentioned earlier in the call"
    }
  ]
}
```

Emitted only when `needs_external_info` is true **and** `confidence >=
detect.min_confidence` (default 0.65).

- **Deduplication**: embed `normalized` and compare against queued items with cosine
  similarity; suppress above `detect.dedup_threshold` (default 0.88).
- **Prompt**: includes the negative examples from §4.1 verbatim. Precision is tuned by
  adding negatives, not by raising the threshold.

### 4.4 Tuning signal

Every state transition is logged locally. The north-star metric is **click-through
rate**: of the questions surfaced, what fraction did the user click?

> **If CTR is below ~30%, the detector is wrong.** Fix the prompt and the negatives
> before building anything further on top of the queue.

CTR, dismissal rate, and resolved-in-conversation rate are visible in Settings so the
user can see whether detection is working for their meetings. Nothing is transmitted.

---

## 5. The question queue

### 5.1 State machine

```
   detected
      │  hold for surface_delay (default 6 s)
      │
      ├──▶ resolved_in_conversation ──┐   (answered by the room during the hold)
      │                               │
      ▼                               │
  surfaced ────▶ resolved_in_conversation
      │                               │   (answered by the room after surfacing)
      │ click                         │
      ▼                               ▼
  answering ────▶ answered      (collapsed "Resolved" section, greyed, not deleted)
      │
      ├──▶ failed  (retryable)
      │
      └──▶ dismissed  (user)          expired (ttl, default 15 min)
```

### 5.2 Surfacing delay

Held for `queue.surface_delay` seconds before becoming visible — **6 s by default**.
Long enough to catch the common case where a colleague answers immediately; short
enough that the question is still live when it appears.

This is deliberately shorter than a purely precision-optimal delay. Per the operating
assumption in §1, the user wants questions to appear while they are still relevant and
to be **corrected afterwards** rather than withheld.

### 5.3 Live resolution

Resolution checking continues **after** surfacing, which is what makes the short delay
safe. Every `queue.resolution_interval` (default 6 s), for each item in `surfaced`:

- Take the transcript since `t_asked`
- Ask the detector model: *has this question now been answered in the conversation?*
- If yes → transition to `resolved_in_conversation`

Resolved items grey out and collapse into a `Resolved (n)` group. They are **not
deleted** — a resolution judgement can be wrong, and the user can reopen one. Items
stop being resolution-checked once `answering` begins.

### 5.4 Ranking and display

Visible items are capped at `queue.max_visible` (default 4), ranked by:

```
score = confidence * recency_decay(t_asked) * (1.4 if has_matching_context else 1.0)
```

`recency_decay` halves every 5 minutes. A question the context packs can clearly answer
ranks above one that would need a blind web search.

Overflow lives behind a `+n more` expander. **No badges, no toasts, no sound.** The
queue must never demand attention; it is glanced at, not notified from.

---

## 6. The answer pipeline

Clicking a question runs route → execute → synthesise. The router decides what to
consult; nothing is hard-wired to RAG or to MCP.

### 6.1 Two tiers

| | Quick answer | Deep agent |
| --- | --- | --- |
| Trigger | Click the question (default) | Click **Dig deeper** |
| Shape | One routing pass, parallel tool calls, one synthesis | Multi-step loop, can chain and re-plan |
| Steps | 1 round of tools | up to `agent.max_steps` (default 8) |
| Target | 5–15 s | 30 s – 3 min |
| Concurrency | counts against the pool | counts against the pool |

Most questions need one lookup. Firing a multi-step agent at *"what's the status of
PROJ-412?"* wastes time and tokens, so the cheap path is the default and escalation is
explicit.

### 6.2 Routing

The router receives the question, the conversation window for context, the attached
context packs with descriptions, the discovered MCP tool schemas, and whether web
search is enabled.

```json
{
  "plan": [
    {"source": "rag",  "pack": "vendor-docs", "query": "migration timeline status"},
    {"source": "mcp",  "server": "jira", "tool": "search_issues",
     "args": {"jql": "project = PROJ AND labels = migration"}},
    {"source": "web",  "query": "acme corp migration announcement 2026"}
  ],
  "rationale": "project state lives in Jira; the timeline doc has the plan of record"
}
```

Rules:

- Plan steps execute **in parallel**; there is no ordering dependency in quick mode
- Maximum `answer.max_sources` steps (default 4)
- An empty plan is valid — the router may answer from conversation context alone
- **Write-capable MCP tools are never selected by the router.** See §8.3

### 6.3 Execution

- All steps dispatched concurrently, each with its own timeout
  (`answer.source_timeout`, default 20 s)
- A failed or timed-out step does not fail the answer; it is recorded and reported
- Results are trimmed to `answer.max_context_tokens` (default 8000), keeping the
  highest-scoring chunks per source

### 6.4 Synthesis

The synthesiser is the largest model the user has configured for the `answer` role.

Output contract:

- Lead with the direct answer — first sentence, no preamble
- Cite each claim to its source: `[vendor-docs: timeline.md]`, `[jira: PROJ-412]`, `[web: url]`
- State explicitly when sources disagree
- **Say "not found in your sources" rather than guessing.** A confident wrong answer
  delivered mid-meeting is the worst possible failure for this product
- Target under 120 words unless the question demands more

Provenance is attached structurally so the UI can render which sources were used and
which of them left the machine (§7.4).

### 6.5 Concurrency

`answer.max_concurrent` (default 3) bounds simultaneous answers. Beyond that, clicks
queue and the item shows `queued`. Each answer is independent; one failing or hanging
never blocks another.

Answers arriving after the conversation has moved on are still written into the queue
item and remain readable. This is what makes the design robust to the assumption in §1
being false.

### 6.6 Delivery

- Renders inline under the question in the panel
- **Copy** — clipboard
- **Paste at cursor** — the existing `output.deliver()` path, unchanged. This is the
  primitive no competitor has: the answer lands in the Slack box you were already
  typing in rather than in a walled overlay

---

## 7. Context and providers

### 7.1 Context packs

A named bundle attached to a meeting.

```yaml
context_packs:
  - name: vendor-docs
    description: Migration plan, vendor contracts, SLA terms   # the router reads this
    sources:
      - type: folder
        path: D:/work/vendor
        include: ["*.md", "*.pdf", "*.docx"]
      - type: url
        url: https://internal.wiki/migration-plan
        refresh: on_attach          # on_attach | daily | manual
      - type: repo
        path: D:/code/platform
        respect_gitignore: true
    mcp: [jira, github]
```

`description` matters — it is what the router uses to decide whether the pack is
relevant. A pack without a useful description will be ignored or over-selected.

### 7.2 Ingestion and retrieval

- **Chunking**: ~500 tokens, 15% overlap, heading-aware for Markdown, page-aware for PDF
- **Embeddings**: `bge-m3` by default. It is multilingual — the Hinglish finding in
  §3.2 applies to retrieval exactly as it applies to transcription, and an
  English-only model like `bge-small-en` will silently underperform on mixed-language
  documents
- **Store**: SQLite with `sqlite-vec`. The corpus is small; a server-based vector
  database is unnecessary complexity
- **Retrieval**: top-k (default 8) by cosine, then keep chunks above a floor rather
  than always returning k
- **Incremental**: hash by file mtime + size; re-embed only what changed

### 7.3 Provider abstraction

Two methods, so a provider is cheap to add:

```python
class Provider(Protocol):
    def chat(self, messages: list[Message], tools: list[Tool] | None = None,
             json_schema: dict | None = None) -> Response: ...
    def embed(self, texts: list[str]) -> list[list[float]]: ...
```

Providers: `ollama`, `openai` (and any OpenAI-compatible endpoint), `anthropic`,
`groq`.

**Roles are configured independently**, because they have genuinely different
requirements:

```yaml
models:
  detector:   {provider: ollama, model: qwen2.5:3b-instruct}   # runs constantly, keep cheap
  router:     {provider: groq,   model: llama-3.3-70b}         # fast, structured output
  answer:     {provider: anthropic, model: claude-sonnet-5}    # quality matters most
  agent:      {provider: anthropic, model: claude-sonnet-5}
  embedder:   {provider: ollama, model: bge-m3}
  summary:    {provider: anthropic, model: claude-sonnet-5}
```

A single-provider preset (all-Ollama, all-OpenAI) ships for people who do not want to
think about this.

### 7.4 What "local-first" means here, precisely

Different parts of the pipeline leave the machine at different rates, and the UI must
be honest about it:

| Stage | Can be fully local | Notes |
| --- | --- | --- |
| Audio capture | Yes | Always local, never transmitted |
| Transcription | Yes | faster-whisper / Parakeet on your GPU |
| Question detection | Yes | Small model via Ollama |
| RAG retrieval | Yes | Local embeddings, local store |
| MCP calls | Depends | A local filesystem server is local; Jira is not |
| Web search | **No** | Inherently leaves the machine |
| Answer synthesis | Yes, with quality cost | See below |

Two commitments:

1. **Per-answer provenance.** Every answer shows which sources it used and flags those
   that left the machine.
2. **Offline mode.** A single toggle restricting the pipeline to local models, local
   RAG, and local MCP servers. Web search and cloud providers are disabled, not
   silently skipped.

**An honest caveat that belongs in user-facing docs:** local models are genuinely fine
for transcription, detection, and retrieval. Multi-step tool-calling agents on a 7B
local model are meaningfully worse than a frontier model, and users will notice.
Ollama support is a real capability, not parity — the docs should say so rather than
letting people discover it during a meeting.

---

## 8. MCP integration

### 8.1 As a client

- Connect to servers over stdio and HTTP
- Discover tools on attach; cache schemas for the session
- Tool schemas are passed to the router, which selects among them
- Failures are isolated: a dead server is skipped and noted in provenance

```yaml
mcp_servers:
  jira:
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-jira"]
    env: {JIRA_URL: "...", JIRA_TOKEN: "${JIRA_TOKEN}"}
    permissions: read_only
```

### 8.2 As a server

LiveWhisper exposes its own MCP server so Claude Code, Claude Desktop, or any MCP client
can read the live meeting:

| Tool | Returns |
| --- | --- |
| `get_live_transcript(channel, last_seconds)` | Recent utterances with speaker labels |
| `list_questions(state)` | The current queue |
| `get_meeting_context()` | Attached packs, participants, elapsed time |
| `get_answer(question_id)` | A completed answer with citations |

Cheap to build, and it makes LiveWhisper composable with the tooling the user already
works in.

### 8.3 Safety

**Write-capable tools are never invoked by the router.** During a live meeting an agent
that files tickets or posts messages unsupervised is a serious liability.

- Servers declare `permissions: read_only` (default) or `read_write`
- Tools from a `read_write` server are split: reads are auto-callable, writes require
  an explicit confirmation dialog naming the tool and showing the arguments
- Confirmation is per-call, never "remember this choice" for writes
- A dry-run log of every proposed write is kept for the meeting

---

## 9. Meeting summary

Generated on meeting end from the **final** transcript of both channels, with speaker
labels. This is why the mic is transcribed and not merely recorded.

Structure:

- **Decisions** — what was settled, and who settled it
- **Action items** — with owner and any stated deadline
- **Open questions** — seeded from queue items that ended `surfaced` or `expired`, i.e.
  the things nobody answered
- **Topics** — brief, with timestamps
- **Answers retrieved** — questions answered during the meeting, with their citations

Output to `transcripts/<timestamp>/`: `summary.md`, `transcript.md`,
`answers.md`, `raw.json`.

---

## 10. UI

The existing recording pill grows into a panel when meeting mode is active.

```
┌────────────────────────────────────────────────────────┐
│ ● 24:13   ▁▃▅▇▅▃▁          vendor-docs · jira    ⚙  ✕ │
├────────────────────────────────────────────────────────┤
│  QUESTIONS                                             │
│                                                        │
│  What's the current status of the vendor migration?    │
│  asked 0:12 ago · jira, vendor-docs      [Answer] [⋯]  │
│                                                        │
│  Which SLA tier did we agree for tier-2 support?       │
│  asked 1:40 ago · vendor-docs            [Answer] [⋯]  │
│                                                        │
│  ▸ Answering: What's our current Postgres version?     │
│    ◐ querying jira, searching vendor-docs…             │
│                                                        │
│  ▸ Resolved in conversation (2)                        │
├────────────────────────────────────────────────────────┤
│  ANSWER · What's our current Postgres version?         │
│  16.3 on the primary cluster, 15.7 on the analytics    │
│  replica. The upgrade to 16 was completed 12 June.     │
│  [infra-docs: databases.md] [jira: OPS-881]            │
│                          [Copy] [Paste at cursor] [⋯]  │
└────────────────────────────────────────────────────────┘
```

Rules:

- Draggable, always-on-top, position remembered — as the pill already is
- Collapses back to the pill; the queue keeps running while collapsed
- `⋯` per item: **Dig deeper**, **Dismiss**, **Edit question**
- **Edit question** matters: the detector's normalisation will sometimes be subtly
  wrong, and letting the user fix the wording before answering is far cheaper than
  making detection perfect
- Optional `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` so the panel stays out of
  shared screens. Framed as **privacy while screen-sharing**, which is what it is
- No notification badges, no sound, no toasts

---

## 11. Configuration

```yaml
meeting:
  enabled: true
  hotkey: ctrl+alt+m

  draft:
    engine: auto              # auto | parakeet | whisper-turbo | none
    max_lag_seconds: 2.0

  detect:
    interval_seconds: 4
    window_seconds: 90
    min_confidence: 0.65
    dedup_threshold: 0.88

  queue:
    surface_delay: 6
    resolution_interval: 6
    ttl_minutes: 15
    max_visible: 4

  answer:
    max_sources: 4
    source_timeout: 20
    max_context_tokens: 8000
    max_concurrent: 3
    web_search: true

  agent:
    max_steps: 8
    timeout_seconds: 180

  offline_mode: false         # local models + local RAG + local MCP only
```

---

## 12. Failure modes

| Failure | Behaviour |
| --- | --- |
| Draft ASR unavailable | Record + final transcript + summary continue; queue disabled with a visible reason |
| Detector model unreachable | Queue disabled, transcription unaffected |
| Detector returns invalid JSON | Retry once, then skip the window |
| MCP server down | Skipped, noted in provenance, answer still produced |
| Provider rate-limited | Fall back down the configured chain; if none, item → `failed`, retryable |
| Answer exceeds timeout | Item → `failed` with partial results retained |
| Very long meeting | Transcript windowed in memory, spilled to disk every 5 min |
| Crash mid-meeting | Audio and partial transcript recoverable from spill files |

---

## 13. Milestones

Each should be independently useful. Do not start one until the previous is genuinely
good.

**M1 — Live transcript.** Channel separation, draft tier, rolling buffer, panel showing
a live two-speaker transcript. No queue yet. Ships value on its own.

**M2 — The queue.** Detection, state machine, surfacing, live resolution. **Answers are
stubbed.** Run it in real meetings and tune CTR to >30% before writing a single line of
the answer pipeline. This is the gate the whole product depends on.

**M3 — Answers from RAG.** Context packs, ingestion, retrieval, router, synthesis,
paste at cursor.

**M4 — MCP client.** Live systems as sources. Read-only, with the write-confirmation
path.

**M5 — Deep agent + parallelism.** Multi-step escalation, concurrent answers.

**M6 — Summary and MCP server.** End-of-meeting output; expose LiveWhisper to Claude
Code.

---

## 14. Open questions

1. **Meeting boundaries.** Detect Zoom/Teams/Meet processes and prompt, or purely
   manual? Auto-detect removes the "forgot to hit record" failure but risks false
   starts.
2. **Cross-meeting memory.** Should past meetings be a retrievable source? Powerful,
   but it turns a session tool into a data store with retention questions attached.
3. **Detector on draft vs. final text.** Draft ASR errors will cause some missed
   questions. Is a second detection pass on the final transcript worth it for the
   summary's open-questions section?
4. **Where the panel lives when collapsed.** Tray only, or a persistent edge-docked
   strip?
5. **Multi-monitor placement** for the panel and the capture-exclusion behaviour.
