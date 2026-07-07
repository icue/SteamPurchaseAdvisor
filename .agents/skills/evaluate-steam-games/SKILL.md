---
name: evaluate-steam-games
description: Evaluate one or more specified Steam games before purchase using regional current and historical-low pricing, current and past bundle context, US subscription-access context, full or user-approved stratified analysis of Steam reviews without a language filter, recent forum discussions, current product-health signals, developer-stated Early Access timelines, and a report localized to the configured report country. Use when the user supplies app IDs or game names and asks whether to buy, analyze, compare, or screen those games, or when filter-steam-wishlist hands off resolved app IDs. Requires a connected Steam Review and Forum MCP server; ITAD data is optional.
---

# Evaluate Steam Games

Produce one localized purchase report per specified game. SteamID and wishlist visibility do not affect this skill. Require the Steam Review and Forum MCP for every report; treat ITAD pricing, bundles, and subscription data as optional.

## Protect repository state during execution

- Treat the repository as read-only during Steam workflow execution except when creating or updating `config.json` after explicit user confirmation. A separate bundle update may modify tracked repository files only after the user explicitly approves an available update and the update-safety policy authorizes the operation.
- Never modify Python files or create helper scripts in the repository. Report bundled-script failures instead.
- Keep temporary state outside the repository. If unavoidable, use one uniquely named path, verify it before cleanup, remove it on success, failure, or cancellation, and report residue.
- Run bundled scripts with Python 3 and `-B`. Do not install dependencies into the repository.

## Resolve inputs, paths, and configuration

1. Accept one or more app IDs, game names, or IDs handed off by another skill.
2. Resolve names from canonical Steam Store `/app/<appid>/` URLs, preferring the official result; ask when multiple games remain plausible.
3. Resolve bundled scripts and `references/` relative to this `SKILL.md`. The repository root is three directories above the skill directory.
4. Resolve shared helpers under `<repo-root>/.agents/lib/steam_purchase_advisor/` and user config at `<repo-root>/config.json`.

At the start of every evaluation, run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/config_status.py
```

## Follow the bundle update policy

The repository root is three directories above this skill directory.

At the start of the first Steam Purchase Advisor workflow in the current conversation or agent run, read and follow:

`<repo-root>/.agents/references/bundle-update-policy.md`

Treat this policy as required workflow instructions. Do not load or apply it again when the current context shows that a sibling Steam Purchase Advisor skill already followed the bundle update policy.

The helper exposes only presence, field errors, countries, and whether the ITAD key exists. When all request-required fields are valid, stay silent about configuration and do not update it. A request-supplied country overrides config only for that request. Never persist overrides automatically or open, print, quote, or expose `itad_api_key`.

When config is absent or a relevant field is missing or invalid:

1. Explain in the user's language that it is local and Git-ignored. Ask only for `report_country`, plus `pricing_country` when ITAD is configured or the user wants pricing. Never request `steam_id`.
2. Use supplied values for the request. Offer one combined confirmation to create or repair only missing or invalid non-secret fields; do not offer to replace valid configured values merely because the request supplied overrides.
3. After confirmation run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/update_config.py [--report-country <CC>] [--pricing-country <CC>]
```

The helper atomically creates the standard shape, preserves `itad_api_key` and unrelated settings, emits no values, and refuses to replace valid fields. Use `--replace-existing` only after the user requests replacement and separately confirms exact field names. Rerun status after updates. If persistence is declined, use request-only values without asking again.

For an ITAD key, direct the user to `https://isthereanydeal.com/apps/` to register an app and edit local config. The scripts ignore OAuth Client ID and Client Secret; link `https://docs.isthereanydeal.com/` for API documentation. Never request the key in chat or CLI. Rerun status and report only configured or not configured.

## Gate all work on MCP readiness

Perform this gate once before ITAD queries or per-game workers.

1. Confirm that a connected Steam Review and Forum MCP advertises `get_steam_game_info`; probe one resolved app ID and reuse its metadata. An application-level `game not found` is not a server outage.
2. If the tool is missing or the probe fails from transport, connection, or timeout, read and follow [the MCP setup procedure](references/mcp-setup.md) completely. If readiness remains unavailable or configuration is declined, stop without querying ITAD or producing a report.

After readiness, obtain or reuse `get_steam_game_info` metadata once per game and derive exactly one release state before preflight or workers:

- `unreleased` when `release_date_coming_soon` is `true`;
- `early-access` when it is `false` and the English `genres` array contains exact value `Early Access`;
- `full-release` when it is `false`, `genres` is available, and lacks `Early Access`;
- `unknown` when required metadata is absent, malformed, or unavailable.

Treat explicit current Steam metadata as authoritative. Never infer Early Access or abandoned development from version numbers, cadence, roadmaps, or community assumptions. For verified `early-access`, retain `release_date_display` as the current Steam-listed start; mark it unavailable when absent or unparseable and do not treat it as immutable history.

## Select countries, language, and titles

- Use `pricing_country` for Steam AppDetails `cc` and ITAD regional prices and bundles. ITAD subscription access always uses the US catalog. Ask only when ITAD is configured and `pricing_country` is missing or invalid. Never configure a currency or perform conversion.
- Use `report_country` to choose the report language. Ask when missing or invalid and ask for a specific language for multilingual countries.
- Resolve one exact runtime `report_language` and matching Steam language code before preflight or workers.

Resolve titles together:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/resolve_steam_titles.py --appids <appid> [<appid> ...] --report-country <CC> [--language <steam-language>]
```

Prefer Steam's selected-language title; otherwise preserve the publisher's original. Never machine-translate titles. Review retrieval is independent of report language: always use `language: "all"` and report only languages observed in the retrieved evidence.

## Preflight review volume and choose modes

Run coordinator-level preflight after country and title resolution, before ITAD, corpora, or analysis workers.

1. For each app ID call `get_steam_review` with `filter: "recent"`, `language: "all"`, `review_type: "all"`, `purchase_type: "all"`, `num_per_page: 1`, `filter_offtopic_activity: 0`, `fetch_all: false`, and `include_review_metadata: false`.
2. Record `query_summary.total_reviews`, or unknown when absent or the call fails.
3. Select `full` automatically for a known count at or below 2,000. For every game above 2,000 or unknown, require the user to choose full retrieval, stratified sampling, or a per-game mapping.
4. Present one localized confirmation for all affected games. Do not create corpora or start analysis until the choice is made; stop if none is made.

Apply the threshold per game, never to a combined total. Parallel preflight workers may return only app ID, resolved title, count or unknown, and a concise failure reason.

## Coordinate multiple games

After modes are fixed, use one parallel worker per game when supported; otherwise run sequentially. Pass app ID, countries, exact languages, title, release state, reused metadata, mode, population count, skill path, and shared ITAD budget. Keep each game's review and forum work in one worker and one report. Keep MCP setup, release classification, preflight, and confirmation in the coordinator.

## Single-game workflow

### 1. Check optional price, bundle, and subscription evidence

Read [the pricing, bundle, and subscription contract](references/pricing-contract.md) completely, then run after MCP readiness:

```text
python -B <skill-dir>/scripts/historical_low_checker.py --appid <appid> [--country <CC>] [--report-country <CC>]
```

Apply every field, failure, identity, regional, comparison, bundle, subscription, Epic giveaway, and shared-quota rule from that contract. Treat ITAD failures as non-fatal. When the key is absent, explain that local `itad_api_key` configuration enables pricing, bundles, subscription data, and Epic giveaway context, mark that evidence unavailable, and continue.

### 2. Analyze reviews

Use the coordinator-selected mode and `language: "all"`.

#### Full mode

1. Call `create_steam_review_corpus` with app ID, `language: "all"`, `review_type: "all"`, `purchase_type: "all"`, `max_reviews: null`, `traversal_mode: "recent"`, `include_review_metadata: true`, and `include_offtopic_activity: true`.
2. Poll `get_steam_review_corpus_status` to completion or failure.
3. Use `aggregate_steam_review_corpus` for overall, positive, negative, trend, and observed-language counts.
4. Page through `query_steam_review_corpus` with bounded `limit` and increasing `offset` until every stored review is processed.
5. Call the analysis exhaustive only when the uncapped corpus completes and exported count is consistent with the available population.

#### Stratified sample mode

1. Create separate positive and negative corpora with `language: "all"`, matching `review_type`, `purchase_type: "all"`, `max_reviews: 1000`, `traversal_mode: "recent"`, `include_review_metadata: true`, and `include_offtopic_activity: true`.
2. Poll both to completion or failure. Use every review when either side has fewer than 1,000; never transfer unused quota.
3. Aggregate separately and page through every stored review.
4. Treat this as a recent sentiment-stratified sample, never random or proportional; do not infer population rating from its positive-to-negative ratio.

For either mode:

- Query at least `review`, `voted_up`, `language`, `timestamp_created`, and `author.playtime_at_review`.
- Maintain four evidence groups: strengths and weaknesses in positive reviews, and weaknesses and strengths in negative reviews.
- Weight recurring, recent, cross-language, and higher-playtime observations over anecdotes; translate or paraphrase into the report language.
- Attach `strong`, `moderate`, or `limited` evidence only when supported by those factors. These labels measure evidence, not quality.
- Report population or unknown, mode, retrieved counts, observed languages, failures, and material limitations. `language: "all"` does not guarantee every language appears in a sample.
- Claim exact theme counts only when counted in retrieved material.

### 3. Build the Early Access timeline and inspect current health

For each `early-access` game run:

```text
python -B <skill-dir>/scripts/early_access_duration_extractor.py --appid <appid>
```

On success read `answer` and `url` from stdout JSON. On nonzero exit preserve structured `reason` and `message` from stderr and continue.

Use the English Store Q&A answer, reused `release_date_display`, and runtime evidence date:

1. Prefer an explicit developer-stated full-release date or window. Otherwise derive a target only from a clear Early Access duration plus a parseable Steam-listed start; add calendar months or years, not fixed day counts.
2. Preserve precision and force: ranges, approximations, conditions, and bounds. Never turn broad or conditional language into an exact date or use unrelated time spans.
3. Compare usable targets with evidence date at matching precision and state only upcoming, within window, or past the stated date or bound. Treat the fetched Store Q&A as current but undated.
4. Preserve explicit targets without a start date. Preserve duration without deriving a date when only the start is missing.
5. Treat extraction failure as non-fatal missing evidence. Distinguish request failure, missing Early Access section, missing standard question, and empty answer; never call these developer refusal.
6. Treat a retrieved but uncalculable answer separately: summarize it and state that no defensible target follows.
7. Use verified official roadmaps or announcements as independent evidence. Identify sources, report unresolved conflicts, and prefer neither unless one explicitly supersedes the other.

Then inspect current discussions and official activity:

1. Call `list_steam_forum_sections`; inspect page 1 of the main board and relevant active sections with `list_steam_forum_topics`. Inspect active `eventcomments` for fixes or operational support and, for Early Access, progress and roadmaps.
2. Treat listing `last_activity_timestamp` and `last_activity_display` only as reply or listing activity. For publication-time claims open the topic with `get_steam_forum_topic` and use `topic.original_post_timestamp`; report unknown when null. Calculate material Early Access update gaps only from verified original-post timestamps.
3. For every game open enough relevant topics to support claims about current bugs, crashes, performance, content, servers, shutdowns, and operational support.
4. For `early-access`, also inspect roadmap progress, verified update gaps, developer communication, closure or layoffs, end-of-development notices, and recurring unfinished-game complaints.
5. For `full-release`, treat sparse updates as neutral. Do not search for routine update gaps, developer silence, missed roadmaps, or halted-development risk. Put material server or support availability, degradation, or shutdown under current issues.
6. For `unknown` or `unreleased`, omit Early Access-only judgments and state the metadata gap only when it limits the recommendation.
7. Separate official evidence from community speculation. Only for `early-access`, classify halted-development risk as `none found`, `low`, `medium`, `high`, or `confirmed`.
8. Preserve direct URLs for opened topics, events, and announcements; prefer direct evidence over section or listing links.

If individual forum calls fail while MCP remains healthy, mark coverage partial and continue.

### 4. Produce the localized report

Read [the purchase report contract](references/report-contract.md) completely immediately before composing each report. Follow its semantic schema, taxonomies, section order, source-link, localization, evidence, and follow-up rules. Base the recommendation on all available evidence and audit the localized report before delivery.
