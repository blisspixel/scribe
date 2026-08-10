# Agentic Balance: Where Scribe Uses Judgment, Where It Uses Rules

This is a decision aid for Scribe changes that make the product "smarter." Read it
when a feature touches transcription, notes, jokes, memes, provider comparison, or
AI evaluation and you are deciding whether to add a deterministic rule or let a
model decide.

Scribe is a local-first desktop CLI, not an agent framework. Its job is to run a
bounded media and analysis pipeline predictably on user hardware. The right balance
is:

> Determinism for pipeline structure and external consequences; model judgment for
> transcript and content quality inside bounded stages; layered evaluation for
> quality instead of regex-style content gates.

## The Axis

Industry guidance draws one useful distinction:

- **Workflow**: model calls and tools follow predefined code paths.
- **Agent**: the model dynamically controls its own process and tool use.

Scribe should stay on the workflow side. It can have model-driven judgment inside
specific stages, but the CLI still owns stage order, retries, file locations,
provider selection rules, and stopping conditions. That puts Scribe in the
"weakly autonomous" zone: the model may decide content within a fixed decision
point, but it does not decide if, when, and how the whole program runs.

## Scribe's Position

Scribe is deliberately not a long-running autonomous agent. The batch path remains:

1. Accept an explicit user command.
2. Validate inputs and configuration.
3. Record, download, convert, or load media.
4. Transcribe with the selected local or API backend.
5. Write structured artifacts.
6. Optionally generate notes, jokes, memes, or provider comparisons.

Future AI features should fit that shape. A model can improve the content produced
inside a stage, but it should not invent new stages, loop without a hard stop,
fetch arbitrary resources, write outside configured output paths, or silently
switch billing modes.

## What Stays a Rule

Keep deterministic code for decisions that are stable, user-facing, or externally
consequential:

- CLI parsing, configuration precedence, and feature flags.
- Recording consent prompts and responsible-use notices.
- URL validation, local/internal address rejection, and cookie-source allowlists.
- File and directory validation, safe filename generation, and atomic writes.
- Media conversion settings, duration and size limits, and temp cleanup.
- Hardware detection, backend selection, and provider capability routing.
- Cost, credential, and provider boundaries.
- Structured artifact validity: JSON schema, VTT/SRT timing validity, Markdown
  frontmatter, and queryable transcript fields.
- Bounded retry loops, maximum QA attempts, request timeouts, and chunk budgets.

These areas do not need model creativity. Rules make them safer, faster, and easier
to test.

## Where Judgment Belongs

Use model judgment where a fixed rule would be a poor proxy for content quality:

- Speech recognition and diarization outputs.
- Meeting-note synthesis: what decisions, blockers, claims, and next steps matter.
- Joke selection, tone matching, and meme concept or caption selection.
- Notes comparison when judging faithfulness, coverage, and usefulness.
- Optional evaluator feedback that improves a content artifact within a bounded
  loop.

The harness should still define the input packet, schema, provider, token budget,
temperature, retry count, and output file. The model decides the content, not the
control flow.

## Do Not Build Quality Moats Out of Regex

Deterministic checks can prove shape. They cannot prove that generated prose is
good, faithful, complete, funny, useful, or on topic.

Allowed deterministic checks:

- Does the JSON parse?
- Are required schema fields present?
- Are transcript timings finite and ordered?
- Does every output file write atomically?
- Is a URL safe to fetch?
- Did a provider response include the fields the adapter requires?

Not allowed as hard ship-time gates:

- "Does this note read like a good executive summary?"
- "Is this action item important enough?"
- "Is this joke funny?"
- "Is this meme caption strong?"
- "Does this local model feel comparable to a cloud model?"

Those are evaluation problems. Push the improvement upstream into prompts,
schemas, examples, and provider configuration; measure it with objective
structure checks plus calibrated model or human evaluation where needed. A regex
that needs a new case whenever the model rephrases has already failed.

## Bound the Loops

Any model-driven loop needs an explicit budget:

- Notes chunking must respect local and cloud context budgets.
- Provider comparison must run only the requested preset or explicit provider list.
- LLM-as-judge is opt-in or selected by a deterministic preset, never required for
  fully offline local comparisons.
- Meme QA can retry only up to the configured attempt count.
- Voice I/O remains an explicit real-time mode, separate from the batch pipeline.

"Let the model keep trying" is not a Scribe design. If a stage needs more attempts,
raise the configured bound intentionally and test the behavior.

## Credential and Billing Boundary

Scribe supports credential transports, not hidden account tunneling:

- Direct provider APIs are allowed when the user supplies an API key or configured
  provider credentials.
- Local providers such as Ollama are allowed when the user runs the local service.
- OpenAI-compatible enterprise or local gateways are allowed when explicitly
  configured through the provider layer.
- Consumer subscription scraping, browser-session reuse, private endpoint
  reverse-engineering, or proxying through unofficial tools is not allowed.

A hosted or local model runner is just another bounded provider. Scribe still owns
the stage sequence, provider selection, input validation, file writes, and output
verification.

## Completion Requires External Evidence

Do not treat "the model said it is done" as completion. A stage is complete when
the harness can verify real behavior:

- The transcript artifact exists and validates against the shared transcript model.
- Structured sidecars parse and can be queried.
- Notes output satisfies the declared schema and, when evaluated, scores against a
  rubric grounded in the transcript.
- Meme output is an image file with locally rendered readable text when local
  overlay is selected.
- Tests cover the deterministic rule, retry, failure, and fallback behavior.

For content quality, use layered evaluation. Structure checks are useful, but they
are only one layer.

## Review Checklist

Before adding an AI feature or quality gate, answer these questions:

1. Does a fixed path actually fail here across normal Scribe use cases?
2. Is the proposed model decision about content inside a stage, or about the
   program's control flow?
3. What external consequence does it touch: spend, egress, disk, credentials, or
   user input devices?
4. What deterministic bounds exist: provider list, token budget, retries, timeout,
   output path, or max attempts?
5. How will quality be measured without turning free-form prose into a regex gate?

If the decision is plumbing, make it a rule. If it is content quality, let the
model judge within a bounded stage and evaluate the result.

## Related Reading

- [Anthropic: Building effective agents](https://www.anthropic.com/research/building-effective-agents)
- [Anthropic: Effective context engineering for AI agents](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents)
- [Anthropic: Effective harnesses for long-running agents](https://www.anthropic.com/engineering/effective-harnesses-for-long-running-agents)
- [NVIDIA: Agentic autonomy levels and security](https://developer.nvidia.com/blog/agentic-autonomy-levels-and-security/)
- [Hugging Face smolagents: What are agents?](https://huggingface.co/docs/smolagents/en/conceptual_guides/intro_agents)
