---
name: evaluate-steam-games
description: Evaluate one or more specified Steam games before purchase using regional current and historical-low pricing, full or user-approved stratified analysis of Steam reviews without a language filter, recent forum discussions, current product-health signals, developer-stated Early Access timelines, and a report localized to the configured report country. Use when the user supplies app IDs or game names and asks whether to buy, analyze, compare, or screen those games, or when filter-steam-wishlist hands off resolved app IDs. Requires a connected Steam Review and Forum MCP server; ITAD pricing is optional.
---

# Evaluate Steam Games

Produce one localized purchase report per specified game. SteamID and wishlist visibility do not affect this skill. Require the Steam Review and Forum MCP for every report; treat ITAD pricing as optional.

## Protect repository state during execution

- Treat the repository as read-only except when creating or updating `config.json` after explicit user confirmation.
- Never modify an existing Python file or create helper scripts in the repository. Report bundled-script failures instead.
- Keep temporary state outside the repository. If repository-local state is unavoidable, use one uniquely named, tracked path; remove it on success, failure, or cancellation after verifying the cleanup target and report any residue.
- Run bundled scripts with Python 3 and `-B`. Do not install dependencies into the repository.

## Resolve inputs, paths, and configuration

1. Accept one or more app IDs, game names, or IDs handed off by another skill.
2. Resolve a game name from its canonical Steam Store URL (`/app/<appid>/`), preferring the official result. Ask when multiple games remain plausible.
3. Resolve `scripts/historical_low_checker.py` and `scripts/early_access_duration_extractor.py` relative to this `SKILL.md` and the repository root three directories above the skill directory.
4. Resolve the config status helper at `<repo-root>/.agents/lib/steam_purchase_advisor/config_status.py`, config update helper at `<repo-root>/.agents/lib/steam_purchase_advisor/update_config.py`, title resolver at `<repo-root>/.agents/lib/steam_purchase_advisor/resolve_steam_titles.py`, and user config at `<repo-root>/config.json`.

At the start of every evaluation request, run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/config_status.py
```

The helper exposes only configuration presence, field errors, countries, and whether the ITAD key exists. When every field needed by the request is valid, do not mention configuration, ask configuration questions, or run the update helper.

A country supplied in the request overrides config for that request only. Never persist overrides automatically or open, print, quote, or expose `itad_api_key`.

When `config.json` is absent or a relevant field is missing or invalid:

1. Explain in the user's language that the file is local and Git-ignored. Ask only for `report_country`, plus `pricing_country` when ITAD is configured or the user wants to configure pricing. Do not request `steam_id`.
2. Use supplied countries for the current request. Offer one combined confirmation to create or repair only the missing or invalid non-secret fields. Do not offer to replace a valid configured value merely because the request supplied an override.
3. After confirmation, run the shared secret-safe update helper with only the approved fields:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/update_config.py [--report-country <CC>] [--pricing-country <CC>]
```

   The helper creates the standard shape when absent, preserves `itad_api_key` and unrelated settings internally, writes atomically, emits only status booleans and field names rather than configuration values, and refuses to replace valid existing fields. Use `--replace-existing` only after the user explicitly requests replacement and separately confirms the exact field names. Rerun the status helper after any update.
4. If the user declines persistence, continue with request-only values and do not ask again during that request.
5. To obtain an ITAD key, direct the user to `https://isthereanydeal.com/apps/` to sign in, register an app, and store the generated key in local config. These scripts do not use the OAuth Client ID or Client Secret. Link `https://docs.isthereanydeal.com/` for API documentation. Never request the key in chat or on the command line; rerun the status helper after the user edits local config and report the key only as configured or not configured.

## Gate all work on MCP readiness

Perform this gate once, before ITAD queries or per-game workers.

1. Confirm that a connected Steam Review and Forum MCP advertises `get_steam_game_info`, then probe one resolved app ID and reuse the metadata. Do not treat an application-level `game not found` result as a server outage.
2. If the tool is missing or the probe fails from transport, connection, or timeout, ask once for permission to automatically register and run the MCP, including a minimal edit to the current client's documented personal MCP configuration outside the repository when dynamic registration is unavailable. Prefer the narrowest non-repository scope that supports the current task. Treat approval as authorization only for that narrowly scoped configuration change; use project or workspace configuration only after separate explicit approval.
3. On approval, verify that the client environment can resolve `npx`. Do not install Node.js, npm, or npx automatically. If `npx` is missing, explain that Node.js 22.19+ with npm is required and stop.
4. Prefer the client's supported dynamic stdio registration. Register command `npx` with arguments `-y` and `steam-review-and-forum-mcp`; do not pin a version.
5. If dynamic registration is unavailable or fails, identify the active client and its version when available, then consult its current official vendor documentation for MCP registration. Prefer an official documentation URL supplied by the user or exposed by the client; otherwise use a focused web search restricted to vendor-owned documentation domains. Do not rely on blogs, forums, search-result snippets, or remembered configuration paths.
6. From the official documentation, determine the client's documented registration command or configuration location, schema, scope, and reload requirements. Do not assume that different clients share a path, format, field names, or reload behavior. If the official documentation is unavailable, conflicting, or ambiguous, do not guess.
7. When the documented mechanism can be applied safely, translate this server specification into the client's own schema: server name `steam-review-and-forum`, stdio command `npx`, and ordered arguments `-y`, `steam-review-and-forum-mcp`. Preserve all unrelated settings, never print the full configuration or expose credentials, and make only the previously authorized server-entry change.
8. Validate the resulting configuration with a parser or the client's native validation facility when available. After a persistent configuration change, tell the user that the client must be refreshed or restarted when hot loading is unavailable. Re-probe and continue only after `get_steam_game_info` becomes callable.
9. Give manual configuration instructions only when the client cannot be identified, official documentation cannot establish a safe native mechanism, the configuration cannot be located or safely written, or both dynamic registration and the documented client-specific path fail. If the user declines configuration or registration remains unavailable, stop without querying ITAD or generating a report.

The MCP client must own the stdio process; never merely launch `npx` in a shell.

After MCP readiness, obtain or reuse `get_steam_game_info` metadata once for every game and derive one release state before preflight or workers:

- `unreleased` when `release_date_coming_soon` is `true`;
- `early-access` when `release_date_coming_soon` is `false` and the English `genres` array contains the exact value `Early Access`;
- `full-release` when `release_date_coming_soon` is `false`, `genres` is available, and it does not contain `Early Access`;
- `unknown` when the required metadata is absent, malformed, or unavailable.

Treat Steam's explicit current metadata as authoritative. Never infer Early Access or abandoned development from version numbers, update cadence, roadmap language, or community assumptions.

For a verified `early-access` game, retain `release_date_display` as the current Steam-listed Early Access start for timeline analysis. Treat it as current Store metadata, not an immutable historical record; mark it unavailable when absent or unparseable.

## Select countries, language, and titles

- Use `pricing_country` for ITAD regional prices. Ask for it only when ITAD is configured and the value is missing or invalid.
- Use `report_country` to choose the report language. Ask when it is missing or invalid, and ask for a specific language when the country is multilingual.
- Resolve one exact runtime `report_language` and matching Steam language code before preflight or workers.

Resolve titles for all app IDs:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/resolve_steam_titles.py --appids <appid> [<appid> ...] --report-country <CC> [--language <steam-language>]
```

Prefer Steam's selected-language title. Preserve Steam's or the publisher's original title when localization is unavailable or lookup fails; never machine-translate a game title.

Review evidence remains independent of the report language. Always use `language: "all"`, and report only languages observed in the retrieved corpus or sample.

## Preflight review volume and choose retrieval modes

Run this coordinator-level preflight after country and title resolution, before ITAD, corpus creation, or analysis workers.

1. For each app ID, call `get_steam_review` with `filter: "recent"`, `language: "all"`, `review_type: "all"`, `purchase_type: "all"`, `num_per_page: 1`, `filter_offtopic_activity: 0`, `fetch_all: false`, and `include_review_metadata: false`.
2. Read `query_summary.total_reviews`; record unknown when absent or when the lightweight call fails.
3. Select `full` automatically for a known count of at most 2,000. Require user choice for each game above 2,000 or unknown: full retrieval, stratified sampling, or a per-game mapping.
4. Present one localized confirmation for all affected games. Do not create their corpora or launch analysis until the user chooses; stop if no choice is made.

Apply the threshold per game, never to a combined total. Lightweight preflight workers may run in parallel but may return only app ID, resolved title, count or unknown, and a concise failure reason.

## Coordinate multiple games

After retrieval modes are fixed, use one parallel worker per game when supported; otherwise process sequentially. Pass the app ID, pricing and report countries, exact `report_language`, Steam language code, resolved title, release state, reused game metadata, retrieval mode, population count, skill path, and shared ITAD budget. Keep one game's review and forum work in one worker and one report. MCP setup, release-state classification, preflight, and user confirmation remain coordinator responsibilities.

## Single-game workflow

### 1. Check optional price history

Run after MCP readiness:

```text
python -B <skill-dir>/scripts/historical_low_checker.py --appid <appid> [--country <CC>] [--report-country <CC>]
```

- When `price_status` is `available`, use `current_price` and the always-present `historical_low_price`; `regular_price` and `discount_percent` may independently be null.
- When it is `unavailable`, preserve `reason`, mark every price signal unavailable, and continue. For `itad_rate_limited`, honor `retry_after` when practical and retry once. Treat other ITAD failures as non-fatal.
- If the key is missing, explain that local `itad_api_key` configuration enables pricing.

Use `discount_percent` as the regional discount rate. Never calculate it from `historical_low_price` or describe that value as a regular price. Compare current with historical low: equal means matching the recorded low, lower means establishing a new low, and higher means above it. Never invent price data or make timing claims from missing signals.

### 2. Analyze reviews

Use the coordinator-selected mode and `language: "all"`.

#### Full mode

1. Call `create_steam_review_corpus` with the app ID, `language: "all"`, `review_type: "all"`, `purchase_type: "all"`, `max_reviews: null`, `traversal_mode: "recent"`, `include_review_metadata: true`, and `include_offtopic_activity: true`.
2. Poll `get_steam_review_corpus_status` to completion or failure.
3. Use `aggregate_steam_review_corpus` for overall, positive, negative, trend, and observed-language counts.
4. Page through `query_steam_review_corpus` with bounded `limit` and increasing `offset` until every stored review is processed.
5. Call the analysis exhaustive only when the uncapped corpus completes and its exported count is consistent with the available population.

#### Stratified sample mode

1. Create separate positive and negative corpora with `language: "all"`, matching `review_type`, `purchase_type: "all"`, `max_reviews: 1000`, `traversal_mode: "recent"`, `include_review_metadata: true`, and `include_offtopic_activity: true`.
2. Poll both corpora to completion or failure. Use every review when one side has fewer than 1,000 and never transfer its unused quota to the other side.
3. Aggregate each corpus separately and page through every stored review.
4. Treat the result as a recent sentiment-stratified sample, not a random or proportional sample; never infer the population rating from its positive-to-negative ratio.

For either mode:

- Query at least `review`, `voted_up`, `language`, `timestamp_created`, and `author.playtime_at_review`.
- Maintain four evidence groups: strengths and weaknesses in positive reviews, and weaknesses and strengths in negative reviews.
- Weight recurring, recent, cross-language, and higher-playtime observations over isolated anecdotes, then translate or paraphrase them into the report language.
- Attach `strong`, `moderate`, or `limited` evidence only to review themes when the retrieved material supports that qualitative evidence judgment. Do not use these labels as game-quality ratings. Weight recurrence, recency, cross-language agreement, and higher-playtime observations as specified in the review-analysis workflow.
- Report population count or unknown, retrieval mode, retrieved counts, observed languages, failures, and material limitations. `language: "all"` removes the language filter but does not guarantee every language appears in a sample.
- Claim exact theme counts only when counted in the retrieved material.

### 3. Build the Early Access timeline and inspect development status

For each `early-access` game, run:

```text
python -B <skill-dir>/scripts/early_access_duration_extractor.py --appid <appid>
```

On success, read `answer` and `url` from stdout JSON. On nonzero exit, read the structured `reason` and `message` from stderr JSON, preserve the source-specific failure, and continue.

Use its English Store Q&A answer with the reused `release_date_display` metadata and the runtime evidence date:

1. Prefer an explicit developer-stated full-release date or window. Otherwise, derive a target only when the answer clearly states the Early Access duration and the Steam-listed start is parseable; add months or years as calendar units rather than fixed day counts.
2. Preserve the statement's precision and force: keep ranges, approximations, conditions, and upper or lower bounds. Do not turn a year, season, broad phrase, or conditional estimate into an exact date, and do not derive a target from ambiguous or unrelated time spans.
3. Compare a usable target with the evidence date at matching precision and state factually whether it is upcoming, currently within its window, or past its stated date or bound. Treat the Store Q&A as current when fetched but undated.
4. If the answer gives an explicit target, use it even when the Steam-listed start is unavailable. If it gives only a duration and the start is unavailable, preserve the duration but do not derive a target date.
5. Treat extractor failures as non-fatal missing evidence. Preserve whether the request failed, the Early Access section was missing, the standard question was missing, or the answer was empty; never describe these failures as the developer declining to provide a timeline. Continue all other evidence collection.
6. Treat a successfully retrieved but uncalculable answer separately from retrieval failure: summarize the statement and say that it does not support a defensible target.
7. Use a verified official roadmap or announcement as independent timeline evidence when available. Identify its source, report unresolved conflicts with the Store Q&A, and prefer neither unless one explicitly supersedes the other.

Then inspect current discussions and official activity:

1. Call `list_steam_forum_sections`, then inspect page 1 of the main board and relevant active sections with `list_steam_forum_topics`. Inspect active `eventcomments` for current fixes or operational-support notices when relevant and, for Early Access games, for development progress and roadmap updates.
2. Treat listing `last_activity_timestamp` and `last_activity_display` only as latest reply or listing activity. For any publication-time claim, open the topic with `get_steam_forum_topic` and use `topic.original_post_timestamp`; report unknown when null. When an Early Access update gap is material, calculate it only from verified original-post timestamps.
3. For every game, open enough relevant topics to support claims about current bugs, crashes, performance, content condition, servers, shutdowns, and operational support.
4. For `early-access` games, also inspect roadmap progress, verified update gaps, developer communication, closure or layoffs, end-of-development notices, and repeated unfinished-game complaints. Calculate update gaps only from verified original-post timestamps.
5. For `full-release` games, treat sparse or absent updates as neutral. Do not search for or report routine update gaps, developer silence, missed roadmaps, or halted-development risk. When ongoing servers or support materially affect use of the purchased product, report verified availability, degradation, or shutdown evidence under current issues rather than as halted development.
6. For `unknown` or `unreleased` release states, omit Early Access-only development judgments. State the metadata gap when it materially limits the recommendation.
7. Separate official evidence from community speculation. Only for `early-access` games, report halted-development risk as `none found`, `low`, `medium`, `high`, or `confirmed`.
8. Preserve direct source URLs returned for opened topics, official events, announcements, and other evidence. Prefer a direct topic or announcement link over a forum-section or listing link.

If individual forum calls fail while MCP remains healthy, mark forum coverage partial and continue.

### 4. Produce the localized report

Include Markdown source links wherever a reliable URL is available, placing each link near the claim it supports. Prioritize links in `🛠️ Is the game healthy right now?`, especially for representative bug or performance discussions, operational support or shutdown notices, and—only for Early Access games—official updates and roadmaps. Never invent, guess, or reconstruct a source URL; leave evidence unlinked when no reliable URL is available.

The following English template is a semantic schema, not literal output. Preserve the section order and the separation between game fit, product state, deal value, and evidence confidence, but omit unsupported or non-material optional findings rather than filling space.

Use emoji selectively as visual navigation and status reinforcement. Emoji must never replace the accompanying text label, status, or explanation and must not introduce a second analytical classification system.

```markdown
# [Localized game title](https://store.steampowered.com/app/<appid>/)

`App <appid>` · **Early Access** · Evidence checked: YYYY-MM-DD

[SteamDB](https://steamdb.info/app/<appid>/) · [ITAD](<itad_url>)

[Include the localized `Early Access` label and its preceding separator only when release state is `early-access`. Omit both for `full-release`, `unreleased`, or `unknown`. Include the `ITAD` link and its preceding separator only when `itad_url` is available from the pricing script.]

> [Coverage notice only when materially relevant: recent sentiment-stratified sample / partial forum coverage / price data unavailable / unknown release state that affects the decision / other decision-relevant limitation.]

## 🎯 Decision

**Recommendation:** 🟢 Buy now / 🟡 Wait for a lower price / 🟡 Wait and reassess / 🔴 Do not buy

**Why:** [One sentence identifying the main reason for the recommendation and the most important condition or caveat.]

| Signal | Assessment | Reason |
|---|---|---|
| **Game fit** | Broad / Taste-dependent / Niche / Unclear | [Who tends to enjoy or reject the core experience, based on review evidence.] |
| **Product state** | Healthy / Watch / Risky / Unknown | [What the current technical, content, or operational support condition means for a buyer; include development condition only for Early Access.] |
| **Deal value** | Strong / Fair / Weak / Unknown | [Whether available price evidence supports paying the current price.] |

**Confidence:** High / Medium / Low — [Brief evidence-coverage reason.]

**Buy if:** [Concrete player preference, tolerance, or use case that supports purchasing.]

**Wait or skip if:** [Concrete deal-breaker, active product issue, or price condition.]

## ⚠️ Before you buy

- **[Most important regret risk]:** [Explain the practical consequence and who should care.]
- **[Second decision-relevant fact]:** [Explain what this means for the buyer.]
- **[Third decision-relevant fact]:** [Explain what this means for the buyer.]

[Use no more than three items. Omit weak or redundant findings.]

## 🎮 Is this game for you?

| ✅ You'll probably enjoy it if... | ⚠️ Think twice if... |
|---|---|
| [Concrete supported preference or playstyle.] | [Specific recurring source of frustration.] |
| [Concrete supported tolerance or expectation.] | [Expectation the game consistently fails to meet.] |
| [Playtime-sensitive or subgroup finding when supported.] | [Relevant sensitivity to a current product issue.] |

## 💬 What players actually say

### What players love

[Choose exactly one format for this subsection. Use the table when there are at least two material themes and every theme fits one concise player-experience sentence without losing important qualifications, caveats, or subgroup context. Otherwise, use bullets for the entire subsection.]

| Theme | Evidence | Player experience |
|---|---|---|
| [Theme] | Strong / Moderate / Limited | [Translate the recurring strength into what the player actually experiences or gains.] |
| [Theme] | Strong / Moderate / Limited | [Buyer consequence.] |

- **[Theme] — Strong / Moderate / Limited evidence:** [Translate the recurring strength into what the player actually experiences or gains.]

### What players criticize

[Choose exactly one format for this subsection. Use the table when there are at least two material themes and every theme fits one concise player-experience sentence without losing important qualifications, caveats, or subgroup context. Otherwise, use bullets for the entire subsection.]

| Theme | Evidence | Player experience |
|---|---|---|
| [Theme] | Strong / Moderate / Limited | [Translate the recurring weakness into its practical effect on the player.] |
| [Theme] | Strong / Moderate / Limited | [Buyer consequence.] |

- **[Theme] — Strong / Moderate / Limited evidence:** [Translate the recurring weakness into its practical effect on the player.]

### Even fans admit

[Weaknesses that recur in positive reviews. Explain why satisfied owners still notice them and, when supported, why they tolerate them.]

### Even critics concede

[Strengths that recur in negative reviews despite the reviewers ultimately not recommending the game.]

### Where players disagree

[Describe genuine disagreements between positive and negative reviewers. State the supported context behind the split, such as playtime, expectations, or another observed factor, when the evidence supports it.]

## 🛠️ Is the game healthy right now?

| Signal | Status | What it means |
|---|---|---|
| **Current issues** | Clear / Watch / Concerning / Unknown | [Short buyer consequence based on current recurring product issues.] |
| **Developer activity** | Active / Sparse / Silent / Unknown | [Early Access only: short factual summary of verified update or communication activity. Omit this row otherwise.] |
| **Halted-development risk** | None found / Low / Medium / High / Confirmed | [Early Access only: short purchasing consequence. Omit this row otherwise.] |

**Early Access timeline:** [Early Access only; always include one localized compact line. When calculable: state the Steam-listed start, developer estimate, derived target/window/bound, and factual position as of the evidence date. When the answer is uncalculable: summarize it and state that no defensible target can be derived. When extraction fails and no independent official target is available: state that the timeline is unavailable and give the localized source-specific limitation. When an independent official target remains available: report it and disclose the Store Q&A limitation. When only the Steam-listed start is missing: preserve an explicit target, or preserve a duration while stating why no target date was derived. Omit this line otherwise.]

**What is happening now:** [Explain current recurring bugs, crashes, performance problems, server concerns, unfinished-content complaints, or that no recurring issue was found in the inspected material. Add direct source links near supported forum claims.]

**What the developer is doing:** [Early Access only: explain recent verified official activity, communication patterns, roadmap information, or gaps. Use exact dates for publication-time claims and add direct source links where available. Omit this paragraph otherwise.]

**What the evidence means:** [Separate verified official evidence from repeated owner reports and community speculation. Explain the practical purchasing consequence.]

## 💰 Is the price right?

| Price signal | Value |
|---|---|
| **Now** | ... / Unavailable |
| **Regular price** | ... / Unavailable |
| **Discount** | ... / Unavailable |
| **Recorded low** | ... / Unavailable |
| **Compared with recorded low** | ✅ Matches recorded low / 🔽 Establishes a new low / ⬆️ Above recorded low / Unavailable |

**Buy timing:** [One plain-language transaction judgment. Explain whether available price evidence supports buying now, waiting for a lower price, or provides insufficient information for confident timing advice. Do not let a historical low override material game-fit or product-state concerns.]

## Evidence and limitations

| Evidence | Coverage |
|---|---|
| **Review population** | ... total / Unknown |
| **Retrieval mode** | Full / Recent sentiment-stratified sample |
| **Reviews retrieved** | ... [total, or positive and negative corpus counts as applicable] |
| **Languages observed** | ... |
| **Review limitations** | [Sampling design, corpus failure, incomplete population comparison, or other material limitation.] |
| **Forum coverage** | [Sections and relevant material inspected; note partial failures.] |
| **Price coverage** | IsThereAnyDeal regional pricing for [country] / Unavailable — [reason] |

**What the gaps prevent me from concluding:** [State exactly which conclusion, if any, cannot be made confidently because of missing evidence.]

## 🔍 Explore further

- [Dynamic question?]
- [Dynamic question?]
- [Dynamic question?]
```

Base recommendations on all available evidence. A historical low does not by itself justify purchase. Preserve the four review evidence groups and state material gaps. Without price data, avoid confident buy-now or wait-for-lower-price timing claims unless the user supplied another explicit source. In sampled mode, identify the design prominently and calibrate confidence to consistency and coverage, not the sampled sentiment ratio.

Treat the report as a buyer's guide rather than an analysis transcript:

* Use buyer-facing section names and explain findings through their practical purchasing consequences.
* Keep the underlying distinctions between game fit, product state, deal value, and evidence confidence explicit in the `🎯 Decision` section.
* Do not convert the decision signals into numeric scores or a hidden aggregate rating.
* Do not add a separate final verdict. The `🎯 Decision` section is the conclusion; later sections explain the evidence behind it.
* Use tables for compact, directly comparable facts, statuses, or review themes. Keep nuanced review findings and decision-relevant caveats in prose or bullets.
* Use emoji only for major section navigation, recommendation reinforcement, fit-table orientation, and factual position-versus-recorded-low reinforcement.
* Emoji must accompany explicit text. Never use emoji alone to communicate a recommendation, status, risk level, evidence strength, or price conclusion.
* Do not add traffic-light emoji to `Game fit`, `Product state`, `Deal value`, `Current issues`, `Developer activity`, `Halted-development risk`, or review evidence-strength labels. Their textual taxonomies are authoritative.
* Do not decorate ordinary review bullets, evidence rows, source links, or methodology fields with emoji.
* Do not manufacture a fixed number of strengths, weaknesses, fit conditions, or risks. Omit weak, unsupported, or non-material findings.
* Keep `⚠️ Before you buy` to the findings most likely to cause buyer's remorse or materially change the purchase decision. Do not repeat findings there solely because they appear later in the report.
* For review findings, preserve all four evidence groups internally: strengths in positive reviews, weaknesses in positive reviews, weaknesses in negative reviews, and strengths in negative reviews. Translate them into `What players love`, `What players criticize`, `Even fans admit`, and `Even critics concede`.
* Attach `strong`, `moderate`, or `limited evidence` only to review themes when the retrieved material supports that qualitative evidence judgment. These labels describe evidence, not game quality.
* Translate each material review theme into a buyer consequence. Prefer `recurring stutter makes the current build a poor fit for frame-sensitive players` over `performance issues`.
* Choose the format independently for `What players love` and `What players criticize`. Use a table only when the subsection has at least two material themes and every theme preserves its important meaning in one concise player-experience sentence. Use bullets for the entire subsection when it has only one material theme or any theme needs multiple sentences, qualifications, caveats, or subgroup context. Never mix a table and bullets within the same subsection.
* In `Where players disagree`, state a reason for the split only when the retrieved evidence supports that context. Do not invent explanations from genre assumptions.
* In the `🎮 Is this game for you?` table, do not force the two columns into opposites or paired comparisons. Each cell is an independent supported fit condition. Leave a cell blank when the columns contain different numbers of material findings.
* In `🛠️ Is the game healthy right now?`, describe the current inspected state and its purchasing consequence. Do not predict that a game will remain healthy for a specific future period.
* Use the derived release state consistently across evidence collection, the decision card, the health section, and exploration questions. Do not let a worker reclassify it from forum activity.
* For every `early-access` game, include the compact `Early Access timeline` line and link its Store Q&A or official timeline source when available. Keep it separate from `Developer activity`; omit it for every other release state.
* Treat timeline position as context, not a recommendation rule. A distant target is neutral by itself, a nearby target is not a buy signal, and a passed estimate is not by itself evidence of halted development.
* Escalate timeline evidence into `Product state`, `Before you buy`, halted-development risk, or the recommendation only when combined with verified progress, update cadence, build condition, roadmap evidence, repeated unfinished-content concerns, or another buyer-relevant factor.
* Do not lower `Product state`, halted-development risk, recommendation, or confidence solely because timeline extraction failed. Lower confidence only when the missing timeline prevents a specific decision-relevant conclusion.
* For `full-release` games, base `Product state` on current technical, content, server, and operational-support evidence. Treat a lack of recent patches or developer posts as neutral and never use it alone to lower `Product state`, recommendation, or confidence.
* For a `full-release` game with a material online or service dependency, report verified server availability, support degradation, or shutdown evidence under `Current issues` and `What is happening now`; do not convert it into a developer-activity or halted-development judgment.
* For `unknown` release state, omit the Early Access label, `Developer activity`, `Halted-development risk`, and `What the developer is doing`. Show a coverage notice only when that uncertainty weakens a decision-relevant conclusion.
* Classify `Current issues` as `clear`, `watch`, `concerning`, or `unknown`:

  * `clear` when no recurring purchase-relevant issue was found in adequately inspected current material;
  * `watch` when issues exist but appear limited, conditional, or actively mitigated;
  * `concerning` when recurring current issues can materially affect purchase suitability;
  * `unknown` when coverage is insufficient.
* Only for `early-access` games, classify `Developer activity` as `active`, `sparse`, `silent`, or `unknown`. This describes verified update or communication activity only and is not itself a product-health rating.
* Preserve the exact price inputs and historical-low semantics from the pricing workflow. The buyer-facing table labels `Now`, `Regular price`, `Discount`, `Recorded low`, and `Compared with recorded low` map respectively to `current_price`, `regular_price`, `discount_percent`, `historical_low_price`, and the required current-versus-historical-low comparison.
* In the price table, `✅`, `🔽`, and `⬆️` only reinforce the explicit recorded-low comparison text. They do not represent overall deal quality or the purchase recommendation.
* `Buy timing` must remain separate from whether the underlying game is a good fit or the current product state is healthy.
* Only for `early-access` games, report halted-development risk as `none found`, `low`, `medium`, `high`, or `confirmed`. Separate official evidence from owner reports and community speculation. Omit the field for every other release state.
* Partial forum coverage must not be presented as evidence that no problem exists. Prefer `no recurring issue was found in the inspected material` when that is the strongest supported statement.
* Show a coverage notice below the title when the report uses a recent sentiment-stratified sample or when a decision-relevant source is materially incomplete.
* Keep material evidence limitations visible in the coverage notice and `🎯 Decision` section when they affect the recommendation. The collapsed `Evidence and limitations` section provides audit detail; it must not be used to hide decision-relevant uncertainty.
* State exactly which conclusion a material evidence gap weakens or prevents rather than lowering all confidence indiscriminately.

Before delivery, the coordinator must enforce the exact runtime `report_language` across worker output:

* Localize every heading, table header, table status value, label, explanation, limitation, evidence summary, and exploration question.
* Translate or paraphrase foreign review and forum material; do not mix untranslated sentences or raw quotes into the body.
* Preserve official game titles, company and personal names, URLs, currency codes, and necessary established acronyms. Use the resolved localized title when available and the official original title otherwise.
* Preserve the template's navigation and reinforcement emoji unless the output environment cannot render them reliably. Localize the accompanying text naturally.
* Localize ordinary template and genre terms; English tokens such as `Recommendation`, `high`, `Full mode`, `Bug`, and `Explore further` must not remain in a non-English report unless part of a proper name or code.
* Localize buyer-facing phrases naturally rather than translating headings word for word when a more idiomatic equivalent exists.
* Audit the final report line by line before delivery.

End each report with a naturally localized, action-oriented `🔍 Explore further` heading:

* Ask exactly three distinct, compact questions, one per line; never exceed 12 English words per question.
* Select each question dynamically from a finding, disagreement, uncertainty, or gap; do not assign a fixed topic, purpose, or evidence source to any question position. Offer only MCP-supported review, forum, event-comment, or metadata exploration. Offer development-activity or roadmap exploration only for verified Early Access games; for full releases, offer operational-support exploration only when continued service materially affects the purchase.
* Do not repeat answered questions or offer price research, alerts, external research, benchmarks, or monitoring.

## Respect the ITAD request limit

Treat ITAD's 1,000 requests per rolling five minutes as one shared API-key budget across workers, wishlist handoffs, and concurrent runs. Estimate two requests per game, include known prior consumption, reserve a safety margin, and never give each worker a separate allowance.
