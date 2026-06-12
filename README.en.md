# Le Chef d'Orchestre (The Conductor) — a fail-closed local/cloud router for AI

> 🇫🇷 [Version française](README.md)

A dispatcher for AI requests: sensitive data stays on your machine (local model),
heavy harmless tasks may go to the cloud. Built during the LE LABO IA workshop
(France, June 2026) around one simple idea: the local/cloud boundary is first a
matter of confidentiality, not performance.

100% open source stack: [LiteLLM](https://github.com/BerriAI/litellm) (gateway) +
[Ollama](https://ollama.com) (local engine) + a permissively licensed model (Qwen, Apache 2.0).

## The idea in one picture

The switchboard operator (LiteLLM) answers every call. A lock (the
`chef_orchestre_hook.py` hook) checks first: does the request contain sensitive
data (email, IBAN, social security number, professional-secrecy vocabulary)?

- **YES -> LOCAL, mandatory.** And if the local model is down: a clean error.
  NEVER a silent fallback to the cloud. That is **fail-closed**: the door breaks
  in the locked position.
- **NO -> cost arbitration.** Heavy task: cloud. Simple task: local (nearly free).

Every decision is written to a log (`journal-routage.jsonl`) WITHOUT the request
content: who decided what, when, why. That is your compliance trail (GDPR
article 32, accountability).

## The golden rule

The SENSITIVITY classifier ALWAYS runs before the cost classifier. When in
doubt: local. Two legal reasons, checked against primary sources:

1. Pseudonymization does not take data out of the personal-data regime for
   whoever keeps the correspondence table (CJEU, 4 September 2025, case
   C-413/23 P, EDPS v SRB; ruled under EU Regulation 2018/1725, reasoning
   transposable to the GDPR).
2. Some recent cloud models retain prompts for at least 30 days with no
   zero-retention option (example: Anthropic's Mythos-class models, official
   documentation on support.claude.com, June 2026). For data covered by
   professional secrecy, the unbeatable answer remains: "it never leaves".

## Contents

| File | Role |
|---|---|
| `config.yaml` | The LiteLLM routing table: `local-sensible`, `cloud-lourd`, `chef-auto`, `cloud-pseudo` routes |
| `greffier.py` | The locked-cabinet method: round-trip pseudonymization, the table never leaves |
| `detection.py` | The brain of the lock: text extraction, sensitivity, complexity (pure Python, zero dependency) |
| `detection_fine.py` | The optional magnifier: fine-grained PII detection (GLiNER or Presidio), sliding windows |
| `chef_orchestre_hook.py` | The LiteLLM plumbing: fail-closed, default-deny, logging |
| `test_detection.py` | 98 unit tests (stdlib only): `python test_detection.py` |
| `vigie.py` | The lookout: diagnoses what falls OUTSIDE the known cases (script, language, unknown identifier) and requests an update |
| `packs-pays/` | Continuous improvement under human GO: per-country detection packs, self-tested on activation |
| `requirements-fine.txt` | Optional magnifier dependencies (pinned versions) |
| `demo.py` | The demonstration (see below) |
| `install/install.sh` / `install.ps1` | Target-machine installation (Linux GPU or Windows) |
| `start.sh` / `start.ps1` | Router startup (Ollama + LiteLLM) |
| `.env.example` | The variables to fill in (keys NEVER go through git) |
| `rideau-presidio/` | The optional second curtain: LiteLLM's Presidio guardrail, local containers + injected French rules |

Note: code comments and log labels are in French (the project was born in a
French regulated-professions context: lawyers, healthcare, accountants). Every
concept is explained in this README; the code itself is short and readable.

## The demo (`demo.py`)

1. **Simple harmless question** -> goes LOCAL (for economy).
2. **Question containing sensitive data** (fake IBAN) -> FORCED local, reason logged.
3. **Fail-closed**: kill the local model, ask the sensitive question again ->
   CLEAN ERROR, zero cloud attempts. This is the proof that matters in front of
   a lawyer.
4. **Heavy harmless task** -> routed to the CLOUD (if a key is present).
5. **Locked-cabinet round trip**: an IBAN leaves as `<IBAN_1>`, the cloud answers
   with the token, the real value is restored locally.
6. **Cabinet refusal**: the word "patient" (context, not a replaceable value)
   makes the pseudonymized route refuse: incomplete pseudonymization never leaves.

## Installation

```bash
git clone https://github.com/chabanade/chef-orchestre-public && cd chef-orchestre-public
cp .env.example .env        # fill in values (never in git, never in a chat)
bash install/install.sh     # installs Ollama + model + LiteLLM
bash start.sh               # starts the router on port 4000
python demo.py              # plays acts 1, 2, 4, 5
python demo.py fail         # act 3, after stopping Ollama
```

On Windows: `install\install.ps1` then `start.ps1`.

Default local model: `qwen3:4b` (Apache 2.0, ~2.6 GB, runs even on CPU).
On a GPU machine, switch to `qwen3:14b` or larger: `OLLAMA_MODEL` in `.env`.

## The magnifier: fine-grained PII detection (optional)

On top of the rule-based lock, a magnifier catches what regexes miss: person
names, addresses, organizations, diagnoses... Default engine:
[GLiNER](https://github.com/urchade/GLiNER) with the `urchade/gliner_multi_pii-v1`
model (Apache 2.0, 6 languages including French, runs on CPU). Variant:
[Microsoft Presidio](https://github.com/microsoft/presidio) (MIT) + French spaCy.

Install: `bash install/install.sh --fine` (or `install.ps1 -Fine`). Settings:
`CHEF_DETECTION_FINE` (gliner / presidio / off) and `CHEF_SEUIL_FIN` in `.env`.

Magnifier safety: it COMPLEMENTS the rules (union), it never replaces them.
Magnifier absent -> rules alone (logged). Magnifier crashing -> the request is
treated as sensitive and stays local: a failure degrades power, never
confidentiality. Long texts are split into overlapping windows (GLiNER only
reads ~384 tokens at once: without chunking, data buried deep in a long
document would be invisible).

### Double-checking (ultra-sensitive data: healthcare, lawyers)

The magnifier is MULTI-ENGINE: `CHEF_DETECTION_FINE=gliner,presidio` runs both
detectors on every request and takes the union of findings. ONE engine seeing a
piece of data is enough to keep it local. Three layers in total: regex rules
(formats: IBAN, SSN, email) + GLiNER (meaning: names, addresses, diagnoses) +
Presidio (patterns and NER, a different angle). Install: `install.sh
--fine-double` (or `install.ps1 -FineDouble`). And `CHEF_LOUPE_STRICTE=1` to
demand that the promised defense be complete: if a requested engine is missing
at startup, everything stays local until it is fixed. Honesty: no combination
reaches 100% recall; truly ultra-sensitive data must stay local BY DEFAULT, the
magnifier only catches what would try to leave.

### Engine choice: market study (12 June 2026)

A comparative study of open source PII detectors usable 100% locally on French
text (landscape, French quality, defense in depth, specialized tools) confirms
this stack as the best free base to date: `gliner_multi_pii-v1` is, as of June
2026, the only zero-shot PII model that is both freely licensed AND with
attested French; Presidio is the reference hybrid framework (its own editor
advocates combining detectors). Lesson applied: default GLiNER threshold at
0.3, because its documented bias is high precision / low recall, the opposite
of what fail-closed requires (a false positive costs one local run, a false
negative costs a leak). French extension candidates (audit before use):
Anonym-IA CamemBERT PII (MIT), NERmembert (MIT), AP-HP's eds-pseudo (BSD-3,
clinical). Discarded: Piiranha (non-commercial license, performance disputed by
arXiv 2504.12308), eu-pii-safeguard (evaluation license), cloud detectors
(asking the cloud whether a piece of data may leave for the cloud violates the
secret by the very act of checking).

## The locked-cabinet method: the `cloud-pseudo` route (round-trip pseudonymization)

Inspired by a real hospital practice (the French CECOS centers, for gamete
donation): each donor gets a number, everyone works with the number and the
useful data (blood type, physical traits), and the real identity stays in a
locked filing cabinet, accessible to very few people, upon justified request.
This is exactly pseudonymization in the GDPR sense (art. 4(5)): re-identification
information kept SEPARATELY, under technical and organizational measures.

The digital transposition (opt-in `cloud-pseudo` route, see `greffier.py`):
1. OUTBOUND: formatted values (IBAN, SSN, email, phone, company IDs, credit
   cards) are replaced by tokens `<IBAN_1>`, `<EMAIL_1>`... The token -> value
   table (the cabinet) stays IN LOCAL MEMORY, never on disk, never in the log.
2. The cloud works on numbers, the way the lab worked on donors.
3. RETURN: the answer is re-personalized locally, then the cabinet is burned
   (the table only lives for the round trip: better than the paper cabinet).

Fail-closed guardrails: after pseudonymization, the text is RE-CHECKED; if any
signal remains (a trade keyword such as "patient", an entity seen by the
magnifier, a non-inspectable block), the request is REFUSED: incomplete
pseudonymization never leaves. Without the hook, the `cloud-pseudo` route
points to the local model (nothing leaves by accident). Streaming is disabled
on this route (re-personalization requires the full response).

Acknowledged legal limits (checked on primary sources): for whoever holds the
table, pseudonymized data REMAINS personal data (CJEU, 4 September 2025,
C-413/23 P); and context can re-identify without any direct identifier (the
Article 29 Working Party criteria: singling out, linkability, inference). This
route strongly REDUCES the risk for mixed tasks; it does not replace strict
local processing for the ultra-sensitive, and data minimization is still owed.

### The SESSION cabinet: iterating without amnesia

With a cabinet burned after every round trip, the router would be amnesic
between two questions of the same conversation (the `<IBAN_1>` of turn 1 would
become unrecoverable at turn 3). So each CONVERSATION gets its own cabinet: the
same value keeps the same token from turn to turn, and a token minted at turn 1
remains restorable at turn 5. Session key: `metadata.session_id` (recommended),
else the standard `user` field, else one shared cabinet (single-user machine).

A deliberate, bounded trade-off: the cabinet lives longer, BUT it stays in the
memory of a single process (never disk, never log), it is BURNED after
`CHEF_ARMOIRE_TTL_MINUTES` of inactivity (30 min by default), the number of
sessions is capped, and a router restart loses it: SAFE degradation (orphan
tokens stay opaque, nothing leaks). `CHEF_ARMOIRE_SESSION=0` restores burning
after every round trip (maximum security, amnesia accepted).

### Comparison with existing tools (study of 12 June 2026)

The clerk was compared with public solutions: LLM Guard (conceptual twin with
its Vault, but English/Chinese only and slowing down), Presidio encrypt/decrypt
(the encrypted secret travels WITH the prompt: a key leak would make archived
prompts decryptable, where a burned table leaves nothing), LiteLLM's native
Presidio guardrail (`output_parse_pii`: a true native round trip, recommended
as a SECOND line of defense, but with no fail-closed refusal), PII-Shield
(interesting French MIT recognizers, table on disk for 7 days), Kong
ai-sanitizer (paid, closed), LangChain PresidioReversibleAnonymizer (archived,
dead). Finding: the combination of native French + burned in-memory table +
fail-closed refusal exists in no public tool to date.

Hardened after the study (main risk: tokens damaged by the model): automatic
system instruction, tolerant matching on return (`<iban 1>`, `< IBAN_1 >`,
`<Iban-1>` are recovered), and logged integrity check (an unrecoverable token
is left opaque: zero leak, zero guessing).

### The study's best ideas, adopted and verified at the source (12 June 2026)

Every idea was checked against the ORIGINAL code before being adopted, and the
detour was worth it. PII-Shield's real code is poorer than its README (NIR
with no validation and less precise than ours, CNI = a bare `\d{12}`, a
passport pattern that misses the actual French format): the real loot was its
IDEA of **contextual patterns** — a pattern too generic to decide alone only
counts when a context word accompanies it. Adopted and improved:

- **French intra-community VAT number** (`FRxx` + SIREN): strong pattern,
  case-insensitive — it was not detected at all before;
- **French ID card** (12 digits + context word) and **French passport** in the
  VERIFIED format (2 digits + 2 letters + 5 digits, source Purview /
  service-public, plus the EU variants): detected by the lock AND tokenized by
  the clerk as defense in depth (a false positive is harmless, the round trip
  restores the value);
- along the way, the looting tests exposed a real collision: the phone-number
  regex was eating the MIDDLE of a VAT number; fixed with a `(?<!\d)` guard
  and a specific-before-generic replacement order;
- **the second curtain is ready** (`rideau-presidio/`): LiteLLM's native
  Presidio guardrail (`output_parse_pii` = its own round trip) in series
  behind the lock — two codebases written by different people don't share the
  same blind spots. Two local Docker containers bound to 127.0.0.1, the
  analyzer extended with French, and the router's French rules injected as ad
  hoc recognizers. Ready to plug in (3 steps, see its README), to be tested on
  the target machine.

### The foreign client (same day, a few hours later)

A French professional has FOREIGN clients: an American passport, a company
headquartered abroad, a cross-border patient. The v1 lock was France-centric;
fixed by format STRUCTURE (not country by country):

- new direct patterns: **EU-wide VAT numbers** (we caught the French one but
  not the German one...), **US SSN** (dashed 3-2-4), **Swiss AVS**
  (756.xxxx), **Italian codice fiscale** (16 structured characters),
  **international phone numbers** (the E.164 `+prefix` or `00` covers every
  country at once), **Amex** 15-digit cards;
- extended contextual patterns: 1-letter + 8-digit passports (recent US),
  UK NINO; discriminating English keywords (confidential, social security,
  medical record, attorney-client...);
- **a serious hole exposed by this very question**: the IBAN regex required
  at least 20 characters — SHORT IBANs (Belgium 16, Netherlands 18, Norway
  15) had been slipping through from day one. Fixed and locked by a test;
- the second curtain enriched accordingly: with `presidio_language: fr`,
  Presidio's native English recognizers (US_SSN...) do not run, so the
  international patterns are also injected into `recognizers-fr.json`
  (11 recognizers).

Honest limit: for names, addresses and context WITHOUT a format (a file
written in German, a foreign patient's name), regexes can structurally do
nothing — that is the job of the magnifier (GLiNER is multilingual:
en/fr/de/es/it/pt, it detects by MEANING) and of the second curtain. On the
final machine, the magnifier is not a comfort option: it is the layer that
covers the foreign cases.

### The lookout and the country packs: the router knows how to say "I don't know"

A protection system that silently BELIEVES it is covered is a danger. The
lookout (`vigie.py`) diagnoses what falls outside the known cases and
REQUESTS its own update:

1. **The alert.** Uncovered script (Cyrillic, Arabic, Chinese... — certain
   detection via Unicode ranges), unidentified Latin language (stop-word
   heuristic, imperfect and documented as such), or unknown identifier (a
   national-identifier-looking sequence that survived the clerk on the
   pseudo route). The request stays LOCAL, the refusal explains what to do,
   the gap is logged in `alertes-couverture.jsonl` (metadata only, never
   the content).
2. **The origin.** The user identifies the document's country.
3. **The GO.** They activate the pack: `CHEF_PACKS_PAYS=bresil` then
   restart. Every pattern in a pack is SELF-TESTED at load time (the regex
   must recognize its own example); a broken pack is refused AS A WHOLE and
   everything stays local until it is fixed.
4. **Resuming.** The CPF becomes `<CPF_BR_1>`, the case file moves on.

Shipped packs (formats verified against Microsoft Purview, 12 June 2026):
Brazil (CPF, CNPJ), India (PAN, Aadhaar), China (18-character resident ID).
Doctrine: the machine DIAGNOSES and REQUESTS, the human DECIDES and
ACTIVATES — a security tool never rewrites its own rules by itself, and a
pack can only ADD detections, never remove any (a safe surface by
construction). Full how-to: `packs-pays/README.md`.

## Hardening from the adversarial review (June 2026)

Three adversarial reviewers (security, concurrency, API accuracy) attacked the
code; every fix is covered by a test:

- **Images and files = sensitive by default.** A non-text block (photo of a
  health card, PDF...) is invisible to regexes: it raises the
  "non-inspectable content" flag and the request stays local (or is refused if
  it targeted the cloud).
- **All call formats covered**: messages, legacy prompt (/completions), input
  (/responses), /v1/messages. A call type the lock cannot inspect that targets
  a non-local route is REFUSED (default-deny).
- **Lowercase IBANs** detected; "iban", "bic" keywords added.
- **Detection failure -> local**, never a 500 error, never the cloud.
- **One magnifier inference at a time** (inference lock) and model loading
  protected against double starts.
- **Hardened configuration**: malformed threshold -> default value; unknown
  magnifier engine (typo) -> magnifier cleanly off, no surprise download.

## Acknowledged limits (honesty)

- The rule-based detector can miss badly formatted sensitive data, and the
  GLiNER magnifier reduces that risk without removing it: no detector is
  perfect. Measure the false-negative rate on YOUR documents before real use.
- The router guarantees WHERE the data goes, not the quality of the local
  model's answer.
- Thresholds (length, keywords) are starting settings, to be calibrated.
- Have every legal statement checked by a lawyer before real professional use:
  this repository is a technical tool, not legal advice.

## License

MIT. Use it well, improve it, share your detectors.
