---
name: evaluate-steam-games
description: Evaluate one or more specified Steam games before purchase using regional current and historical-low pricing, full or user-approved stratified analysis of Steam reviews without a language filter, recent forum discussions, development-status signals, and a report localized to the configured report country. Use when the user supplies app IDs or game names and asks whether to buy, analyze, compare, or screen those games, or when filter-steam-wishlist hands off resolved app IDs. Requires a connected Steam Review and Forum MCP server; ITAD pricing is optional.
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
3. Resolve `scripts/historical_low_checker.py` relative to this `SKILL.md` and the repository root three directories above the skill directory.
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

After retrieval modes are fixed, use one parallel worker per game when supported; otherwise process sequentially. Pass the app ID, pricing and report countries, exact `report_language`, Steam language code, resolved title, retrieval mode, population count, skill path, and shared ITAD budget. Keep one game's review and forum work in one worker and one report. MCP setup, preflight, and user confirmation remain coordinator responsibilities.

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
- Report population count or unknown, retrieval mode, retrieved counts, observed languages, failures, and material limitations. `language: "all"` removes the language filter but does not guarantee every language appears in a sample.
- Claim exact theme counts only when counted in the retrieved material.

### 3. Inspect recent discussions and development status

1. Call `list_steam_forum_sections`, then inspect page 1 of the main board and relevant active sections with `list_steam_forum_topics`. Inspect active `eventcomments` for official updates when available.
2. Treat listing `last_activity_timestamp` and `last_activity_display` only as latest reply or listing activity. For any publication-time claim, open the topic with `get_steam_forum_topic` and use `topic.original_post_timestamp`; report unknown when null. Calculate update gaps only from verified original-post timestamps.
3. Open enough relevant topics to support claims about bugs, crashes, performance, content, updates, roadmaps, developer communication, servers, and support.
4. Check for missed roadmaps, unexplained update gaps, developer silence, closure or layoffs, end-of-support or shutdown notices, and repeated unfinished-game complaints.
5. Separate official evidence from community speculation. Report halted-development risk as `none found`, `low`, `medium`, `high`, or `confirmed`.
6. Preserve direct source URLs returned for opened topics, official events, announcements, and other evidence. Prefer a direct topic or announcement link over a forum-section or listing link.

If individual forum calls fail while MCP remains healthy, mark forum coverage partial and continue.

### 4. Produce the localized report

Include Markdown source links wherever a reliable URL is available, placing each link near the claim it supports. Prioritize links in `Recent community and development status`, especially for official updates, roadmaps, support or shutdown notices, and representative bug or performance discussions. Never invent, guess, or reconstruct a source URL; leave evidence unlinked when no reliable URL is available.

The following English template is a semantic schema, not literal output:

```markdown
# [Game title](https://store.steampowered.com/app/<appid>/)
[SteamDB](https://steamdb.info/app/<appid>/)

## Purchase recommendation
- Recommendation: buy now / wait for a lower price / wait and reassess / do not buy
- Confidence: high / medium / low
- One-sentence rationale: ...

## Price signal
- Current price: ... / unavailable
- Regular price: ... / unavailable
- Discount rate: ... / unavailable
- Historical-low reference price: ... / unavailable
- Historical-low status: matches recorded low / establishes a new low / above recorded low / unavailable
- Interpretation: ...

## All-language review analysis
- Coverage: population total or unknown, full or stratified-sample mode, retrieved counts, observed languages, and limitations
- Main strengths: ...
- Weaknesses mentioned in positive reviews: ...
- Main weaknesses: ...
- Strengths mentioned in negative reviews: ...
- Consensus and disagreements: ...

## Recent community and development status
- Recent discussions: ...
- Halted-development risk: none found / low / medium / high / confirmed
- Evidence: ...

## Suitable and unsuitable players
- Suitable for: ...
- Not suitable for: ...

## Final assessment
...

## Explore further
Do you want to know:
- ...
```

Base recommendations on all available evidence. A historical low does not by itself justify purchase. Preserve the four review evidence groups and state material gaps. Without price data, avoid confident buy-now or wait-for-lower-price timing claims unless the user supplied another explicit source. In sampled mode, identify the design prominently and calibrate confidence to consistency and coverage, not the sampled sentiment ratio.

Before delivery, the coordinator must enforce the exact runtime `report_language` across worker output:

- Localize every heading, label, status value, explanation, limitation, evidence summary, and exploration question.
- Translate or paraphrase foreign review and forum material; do not mix untranslated sentences or raw quotes into the body.
- Preserve official game titles, company and personal names, URLs, currency codes, and necessary established acronyms. Use the resolved localized title when available and the official original title otherwise.
- Localize ordinary template and genre terms; English tokens such as `Recommendation`, `high`, `Full mode`, `Bug`, and `Explore further` must not remain in a non-English report unless part of a proper name or code.
- Audit the final report line by line before delivery.

End each report with a naturally localized, action-oriented `Explore further` heading:

- Ask one compact question per line, preferably two for one game and one per game in a multi-game response; never exceed three or roughly 12 English words per question.
- Tie each question to a finding, disagreement, uncertainty, or gap and offer only MCP-supported review, forum, development-activity, event-comment, or metadata exploration.
- Do not repeat answered questions or offer price research, alerts, external research, benchmarks, or monitoring.

Examples: `Did recent patches fix the reported stuttering?`; `Does repetition vary by playtime?`; `Any recent roadmap activity?`

## Respect the ITAD request limit

Treat ITAD's 1,000 requests per rolling five minutes as one shared API-key budget across workers, wishlist handoffs, and concurrent runs. Estimate two requests per game, include known prior consumption, reserve a safety margin, and never give each worker a separate allowance.
