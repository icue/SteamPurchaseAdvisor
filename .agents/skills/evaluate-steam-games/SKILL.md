---
name: evaluate-steam-games
description: Evaluate one or more specified Steam games before purchase using regional current and historical-low pricing, current and past bundle context, full or user-approved stratified analysis of Steam reviews without a language filter, recent forum discussions, current product-health signals, developer-stated Early Access timelines, and a report localized to the configured report country. Use when the user supplies app IDs or game names and asks whether to buy, analyze, compare, or screen those games, or when filter-steam-wishlist hands off resolved app IDs. Requires a connected Steam Review and Forum MCP server; ITAD deal data is optional.
---

# Evaluate Steam Games

Produce one localized purchase report per specified game. SteamID and wishlist visibility do not affect this skill. Require the Steam Review and Forum MCP for every report; treat ITAD pricing and bundle context as optional.

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

- Use `pricing_country` for both Steam AppDetails (`cc`) and ITAD regional prices. Do not pass or configure a currency: require Steam's returned currency to match ITAD's returned currency exactly and never convert between them. Ask for `pricing_country` only when ITAD is configured and the value is missing or invalid.
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

### 1. Check optional price and bundle history

Run after MCP readiness:

```text
python -B <skill-dir>/scripts/historical_low_checker.py --appid <appid> [--country <CC>] [--report-country <CC>]
```

Standalone price, sale, and historical-low analysis covers only the Steam Store (`price_scope: "steam"`). Bundles are the explicit non-Steam exception and retain their existing multi-store coverage.

- When `price_status` is `available`, use `current_price`; `regular_price` and `discount_percent` may independently be null. Use the Steam-store-only `historical_low_price` only when `steam_low_status` is `available`, and compare it with the current price only when `steam_low_comparison_status` is `available`.
- When it is `unavailable`, preserve `reason`, mark every price signal unavailable, and continue. For `itad_rate_limited`, honor `retry_after` when practical and retry once. Treat other ITAD failures as non-fatal.
- If the key is missing, explain that local `itad_api_key` configuration enables pricing and bundle context.
- Preserve `steam_low_reason`, `steam_low_message`, and `steam_low_retry_after` when the Steam low is unavailable. Preserve `steam_low_comparison_reason` and `steam_low_comparison_message` when a valid low cannot be compared with the current price.
- Current price, Steam store low, Steam-low comparison, Steam history, and bundles fail independently; a failure in one does not suppress valid evidence from the others.

The script resolves the Steam app product and associated Steam package products in one ITAD lookup. For standalone pricing, it requires ITAD's current Steam offer to match the regional Steam AppDetails currency plus initial and final minor-unit amounts. Prefer the matching app identity. Only when it does not match, accept a base-price package from Steam's purchase options; accept multiple matching packages only when they map to one ITAD identity, and otherwise mark standalone pricing ambiguous. Never choose by ITAD response order or title. Query store low and history only for the selected identity. Query bundle history for every distinct resolved identity and deduplicate bundles by ITAD bundle ID.

- When `bundle_status` is `available`, use `bundle_summary`, every `active_bundles` entry, and the already-limited `historical_bundles` list. Omit bundle content when there are no active or historical bundles to report.
- When `bundle_status` is `partial`, use the returned active and historical bundles but disclose the precise coverage failure under evidence limitations. Summarize the count of unknown-status records as a coverage limitation without listing those records as bundle rows. Do not turn partial coverage into a no-bundle claim.
- When `bundle_status` is `unavailable`, preserve `bundle_reason`, omit bundle claims, and disclose the failure under evidence limitations only when it affects deal timing.
- Treat `qualifying_tier_prices` as listed bundle-tier totals. A null amount or currency means variable or unrecorded pricing. The `note` may describe selection counts, build-your-own rules, or other material terms; paraphrase it and never imply that every eligible game is included.
- Link bundle titles only with the API-provided `details_url`. Link `offer_url` only for an active bundle; never reuse an expired offer URL.

Use `discount_percent` as the regional discount rate. Never calculate it from `historical_low_price` or describe that value as a regular price. Compare current with historical low: equal means matching the recorded low, lower means establishing a new low, and higher means above it. Never invent price data or make timing claims from missing signals.

Preserve every ITAD amount and ISO currency exactly; never convert bundle currencies. Numerically compare an active bundle with the standalone price only when exactly one qualifying tier has a non-null amount and currency and that currency matches `current_price.currency`. Treat mismatched currencies, multiple qualifying prices, and missing prices as not directly comparable. Never treat a historical bundle tier as a standalone historical low.

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

[When at least one active bundle contains this game, insert the following as the first item, before regret risks. Include it regardless of the bundle's currency, price-competitiveness, or comparability with the standalone price:]

- **🎁 Active bundle available:** [Name the bundle with its ITAD details link. State the provider, listed qualifying-tier price with currency (or "variable / not recorded"), and expiry. When multiple active bundles exist, name each one briefly. Direct the reader to `Bundle context` for full terms.]

- **[Most important regret risk]:** [Explain the practical consequence and who should care.]
- **[Second decision-relevant fact]:** [Explain what this means for the buyer.]
- **[Third decision-relevant fact]:** [Explain what this means for the buyer.]

[The active-bundle item does not count toward the three-item limit for regret risks and decision-relevant facts. The three-item cap applies only to the remaining findings. Omit the bundle item when no active bundle is available. Omit weak or redundant findings.]

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
| **Steam recorded low** | ... and date / Unavailable |
| **Compared with recorded low** | ✅ Matches recorded low / 🔽 Establishes a new low / ⬆️ Above recorded low / Unavailable |
| **Exact-low recurrence** | Recurring / Recent isolated / Aging / Stale isolated / Stale previously repeated / Insufficient |
| **Recurring realistic sale level** | ... / None found / Unavailable |
| **Sustained list-price change** | ↑ Increased from ... to ... on date (+...%) / ↓ Decreased from ... to ... on date (−...%) / None detected / Ambiguous / Insufficient |

**Bundle context:**

[Omit this subsection completely when there are no active or historical bundles to report. Otherwise, show all active bundles and up to the three historical bundles already returned by the pricing script. State the known historical total when `historical_bundles_truncated` is true. Report unknown-status records only as a coverage limitation, not as bundle rows.]

| Bundle | Availability | Provider | Listed qualifying tier |
|---|---|---|---|
| [Bundle title](<details_url>) [· Offer](<offer_url>) | Active until ... / Ended ... | ... | ... / Variable or not recorded / Not directly comparable |

[Include the `Offer` link only for active bundles. Explain material selection or build-your-own terms from `note`. State that listed tier totals are bundle prices rather than standalone game prices. Preserve currencies and do not perform FX conversion.]

**Deal value:** [Explain how the current price compares with the recurring realistic sale level and the recorded Steam low, factoring in any sustained list-price change that shifted the relevant historical regime. Do not let a historical low override material game-fit or product-state concerns.]

**Buy timing:** [One plain-language transaction judgment. Explain whether available price evidence supports buying now, waiting for a lower price, or provides insufficient information for confident timing advice. A stale isolated record alone must not support waiting; prefer the recurring current-regime sale level. Being above a lower recurring level supports waiting. Repricing changes which historical regime is relevant and must be explained here, but must not independently alter game fit or product health. Pre-change lows remain factual but are not presented as realistic current-regime targets. Missing or ambiguous history prevents recurrence and repricing claims without suppressing a valid current Steam price.]

## Evidence and limitations

| Evidence | Coverage |
|---|---|
| **Review population** | ... total / Unknown |
| **Retrieval mode** | Full / Recent sentiment-stratified sample |
| **Reviews retrieved** | ... [total, or positive and negative corpus counts as applicable] |
| **Languages observed** | ... |
| **Review limitations** | [Sampling design, corpus failure, incomplete population comparison, or other material limitation.] |
| **Forum coverage** | [Sections and relevant material inspected; note partial failures.] |
| **Price coverage** | Steam Store-only via IsThereAnyDeal for [country] / Unavailable — [reason] |
| **Steam history** | Available — [episode count] sale episodes / Unavailable — [reason] |
| **Bundle coverage** | [Include only for partial/unavailable coverage or when bundles are reported: complete / partial — reason / unavailable — reason.] |

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
* Keep `⚠️ Before you buy` to the findings most likely to cause buyer's remorse or materially change the purchase decision. Do not repeat findings there solely because they appear later in the report. The conditional active-bundle notice is an intentional cross-reference that directs the reader to `Bundle context`; it is not subject to this repetition rule.
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
* Preserve the exact price inputs and historical-low semantics from the pricing workflow. The buyer-facing table labels `Now`, `Regular price`, `Discount`, `Steam recorded low`, and `Compared with recorded low` map respectively to `current_price`, `regular_price`, `discount_percent`, `historical_low_price` with `steam_low_timestamp`, and the required current-versus-historical-low comparison. `Exact-low recurrence` maps to `exact_low_pattern`. `Recurring realistic sale level` maps to `recurring_sale_price`. `Sustained list-price change` maps to `list_price_change`.
* In the price table, `✅`, `🔽`, and `⬆️` only reinforce the explicit recorded-low comparison text. They do not represent overall deal quality or the purchase recommendation.
* A stale isolated record alone must not support waiting; prefer the recurring current-regime sale level when available. Matching a recurring level supports buying on price; being above a lower recurring level supports waiting.
* A sustained list-price change shifts which historical regime is relevant. Explain this in `Deal value` and `Buy timing` but do not independently alter game fit or product health. Pre-change lows remain factual but are not presented as realistic current-regime targets.
* Missing or ambiguous history prevents recurrence and repricing claims without suppressing a valid current Steam price.
* Place full bundle details and bundle history in the optional `Bundle context` subsection under `💰 Is the price right?`, then weigh their transaction consequence in `Deal value` and `Buy timing`. When at least one active bundle exists, surface a brief notice in `⚠️ Before you buy` as described in that section's template, directing the reader to `Bundle context` for details.
* Show every active bundle and no more than the three historical bundles returned by the script. Use the known historical total to disclose omitted older entries. Do not show unknown-status records as bundle rows; summarize their count under bundle coverage. Omit the subsection when there are no active or historical bundles to report.
* Describe a tier amount as a listed qualifying bundle tier, never as a standalone game price or per-game value. Preserve material build-your-own, selection-count, addon, or variable-price conditions and link the ITAD details page near the row.
* Never perform currency conversion. Compare an active bundle numerically with `current_price` only when there is exactly one unambiguous non-null qualifying amount and both currencies match. Otherwise state that the prices are not directly comparable.
* A clearly priced active bundle at or below the standalone price may support choosing the bundle, but mention its tier or selection requirements. A more expensive active bundle matters only when its additional content is valuable to the buyer.
* Define recent bundle history as at least one expiry within 365 days of the evidence time. Define recurrent recent history as at least two expiries within 730 days, including one within 365 days; use the script's summary fields rather than recalculating loosely.
* Only when the standalone price is above its recorded low may recent or recurrent bundle history lower `Deal value` by at most one level or support waiting. Bundle history must not weaken the recommendation when the standalone price matches or establishes its recorded low. Older history is context only and never evidence that another bundle will occur.
* Never compare a historical bundle tier with the standalone current price or recorded low, even when currencies match. It describes a different multi-product transaction.
* Treat `bundle_status: partial` as known incomplete coverage: report returned records, disclose the limitation, and never claim that no other bundle exists. Treat `bundle_status: unavailable` as missing evidence rather than a no-bundle result.
* `Buy timing` must remain separate from whether the underlying game is a good fit or the current product state is healthy.
* Only for `early-access` games, report halted-development risk as `none found`, `low`, `medium`, `high`, or `confirmed`. Separate official evidence from owner reports and community speculation. Omit the field for every other release state.
* Partial forum coverage must not be presented as evidence that no problem exists. Prefer `no recurring issue was found in the inspected material` when that is the strongest supported statement.
* Show a coverage notice below the title when the report uses a recent sentiment-stratified sample or when a decision-relevant source is materially incomplete.
* Keep material evidence limitations visible in the coverage notice and `🎯 Decision` section when they affect the recommendation. The `Evidence and limitations` section provides audit detail; it must not be used to hide decision-relevant uncertainty.
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

Treat ITAD's 1,000 requests per rolling five minutes as one shared API-key budget across workers, wishlist handoffs, and concurrent runs. For each game, estimate `4 + A` normal ITAD requests, where `A` is the number of distinct ITAD identities resolved from its Steam app and package products: one product lookup, one Steam-filtered price overview, one Steam store low, one Steam price history, and one bundle-history request per identity. Allow up to `A` additional active-bundle requests only when expiry values are missing or malformed. The one regional Steam AppDetails request used for identity validation does not consume the ITAD quota. Include known prior consumption, reserve a safety margin, and never give each worker a separate allowance.
