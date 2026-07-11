# Pricing, bundle, and subscription contract

Read this file completely before running `historical_low_checker.py` or interpreting its output.

## Contents

- Regional identity and scope
- Independent evidence statuses
- Report field mappings and timing judgments
- Bundle interpretation
- Subscription interpretation
- Epic giveaway interpretation
- Shared request budget

## Regional identity and scope

Use `pricing_country` for Steam AppDetails `cc` and ITAD regional prices and bundles. Do not pass a currency. Preserve every amount and ISO currency exactly and never perform FX conversion.

Standalone price, sale, and historical-low analysis is Steam Store-only (`price_scope: "steam"`). Bundles are the explicit multi-store exception.

Epic Games Store giveaway history is a separate informational exception. It is not Steam price evidence and never changes Recommendation, Deal value, Product state, Confidence, or Buy timing.

The script resolves the Steam app and associated Steam packages in one ITAD lookup. Require the current Steam offer to match regional Steam AppDetails currency plus initial and final minor-unit amounts exactly. Prefer the matching app identity. Only when it does not match, accept a base-price package from Steam purchase options. Accept multiple matching packages only when they resolve to one ITAD identity; otherwise mark standalone pricing ambiguous. Never choose by response order or title.

Query store low and history for the exactly matched identity, or the sole distinct identity when current overview is unavailable. When multiple identities remain without an exact match, mark low and history unavailable rather than guessing. Query bundle history for every distinct resolved identity and use the script's deduplicated output.

## Independent evidence statuses

- When `price_status` is `available`, use `current_price`; `regular_price` and `discount_percent` may independently be null.
- When `price_status` is `unavailable`, preserve `reason`, mark current price, regular price, and discount unavailable, and continue. If exactly one identity was resolved, a non-rate-limit current-overview failure does not suppress a valid Steam low or history result.
- Use `historical_low_price` only when `steam_low_status` is `available`; use `steam_low_timestamp` as its date. Compare it with current price only when `steam_low_comparison_status` is `available`.
- Preserve `steam_low_reason`, `steam_low_message`, and `steam_low_retry_after` when the low is unavailable. Preserve `steam_low_comparison_reason` and `steam_low_comparison_message` when comparison fails. Use `current_price_unavailable` when a low exists without current price.
- After product lookup, current price, Steam low, low comparison, Steam history, bundles, and subscriptions normally fail independently. A shared ITAD rate limit, missing Steam metadata, or an unresolved or ambiguous identity may suppress dependent signals.
- Epic giveaway lookup has its own status after a direct Steam app ITAD identity is resolved, or after a Steam-matched ITAD identity is selected when no direct app identity exists. Missing Steam metadata, unresolved or ambiguous identity, or an earlier rate limit can prevent the lookup. Preserve `epic_giveaway_status`, `epic_giveaway_reason`, `epic_giveaway_message`, and `epic_giveaway_retry_after`. Never treat an empty, partial, or failed Epic result as evidence that no giveaway occurred.
- ITAD helpers do not retry automatically. For `itad_rate_limited`, honor an exposed `retry_after` when practical and rerun the checker once. Treat other ITAD failures as non-fatal. Never invent missing price evidence.

## Report field mappings and timing judgments

Map buyer-facing fields exactly:

| Report field | Script field and null behavior |
|---|---|
| Now | `current_price`; otherwise Unavailable |
| Regular price | `regular_price`; otherwise Unavailable |
| Discount | `discount_percent`; otherwise Unavailable |
| Steam recorded low | `historical_low_price` when `steam_low_status` is available; include `steam_low_timestamp` when non-null, otherwise mark only the date Unavailable |
| Compared with recorded low | When `steam_low_comparison_status` is available, compare `current_price.amount` with `historical_low_price.amount`: equal = Matches, lower = Establishes a new low, higher = Above; otherwise Unavailable |
| Exact-low recurrence | `exact_low_pattern`; map explicit `insufficient` to Insufficient and null to Unavailable |
| Recurring realistic sale level | `recurring_sale_price`; map null to None found only when Steam history and regular price are available, otherwise Unavailable |
| Sustained list-price change | `list_price_change`; map explicit types to matching states and null to Unavailable |
| Epic giveaway context | Include only when `epic_giveaway_detected` is true; omit otherwise |

Use `discount_percent` as the regional discount rate. Never derive it from `historical_low_price` or call the low a regular price. The comparison emoji `✅`, `🔽`, and `⬆️` may reinforce explicit comparison text only; they do not rate deal quality or the game.

Base transaction timing on realistic current-regime evidence:

- Matching a recurring sale level supports buying on price; being above a lower recurring level supports waiting.
- A stale isolated low alone never supports waiting.
- A sustained list-price change shifts the relevant historical regime. Explain it in Deal value and Buy timing, but do not alter game fit or product health. Keep pre-change lows factual without presenting them as realistic current targets.
- Missing or ambiguous history prevents recurrence and repricing claims without suppressing a valid current price.
- Missing price data prevents confident buy-now or wait-for-lower timing advice unless the user supplied another explicit source.
- Keep Buy timing separate from whether the game is a good fit or healthy.

## Bundle interpretation

- For `bundle_status: available`, use `bundle_summary`, every `active_bundles` entry, and the already limited `historical_bundles` list. Omit bundle content when neither active nor historical records exist.
- For `bundle_status: partial`, report returned records, disclose the precise coverage failure, and summarize unknown-status record count without listing those records. Never claim no other bundle exists.
- For `bundle_status: unavailable`, preserve `bundle_reason`, omit bundle claims, and disclose missing coverage when it affects deal timing. Treat unavailable as missing evidence, not evidence of no bundle.
- Show every active bundle and no more than the three historical records returned. When `historical_bundles_truncated` is true, state the known historical total.
- Treat `qualifying_tier_prices` as bundle-tier totals, never standalone or per-game prices. Null amount or currency means variable or unrecorded. Paraphrase material selection-count, build-your-own, addon, or variable-price conditions from `note`; never imply every eligible game is included.
- Link titles only with API `details_url`. Include `offer_url` only for active bundles and never reuse an expired offer URL.

Compare an active bundle numerically with `current_price` only when exactly one qualifying tier has a non-null amount and currency matching `current_price.currency`. Multiple prices, missing prices, or currency mismatch are not directly comparable. Never numerically compare historical bundle tiers with standalone current price or recorded low.

A clearly priced active bundle at or below standalone price may support choosing it, subject to tier or selection requirements. A higher-priced bundle matters only when its additional content is valuable to the buyer.

Use the script summary fields for history. Recent means at least one expiry within 365 days of evidence time. Recurrent recent means at least two expiries within 730 days, including one within 365 days. Only when standalone price is above its recorded low may recent or recurrent history lower Deal value by at most one level or support waiting. Bundle history must not weaken the recommendation when standalone price matches or establishes its low. Older history is context only and never predicts another bundle.

When any active bundle exists, place a brief notice first in `⚠️ Before you buy` and direct the reader to Bundle context. Keep full terms and history in the optional Bundle context subsection under `💰 Is the price right?`.

## Subscription interpretation

Query `/games/subs/v1` with `country=US`, independent of `pricing_country`; the endpoint has no currency parameter. Subscription access is context, not price evidence. Never compare it numerically with Steam prices or bundle tiers, and never use it to change Recommendation, Deal value, Buy timing, Product state, or Confidence.

Use only ITAD IDs mapped from the direct `app/<appid>` product and Steam AppDetails `base_package_products`. Query every distinct safe ID together, merge the records, and exclude every other package alias. This supports package-backed base games without allowing deluxe editions, multipacks, bundles, or DLC collections to supply subscription context.

Interpret the primary fields as follows:

- `subscription_status: available` means the US response was valid. `subscriptions` may be empty; an empty list is not a buyer-facing finding and must produce no subscription content in the report. It never establishes that the game is absent from every subscription service.
- `subscription_status: partial` means the response completed with one or more malformed, expired, or conflicting records; any valid records were retained. Preserve `subscription_reason`, `subscription_message`, and `subscription_errors`.
- `subscription_status: unavailable` means no safe identity was resolved or the request failed. Preserve `subscription_reason`, `subscription_message`, and `subscription_retry_after`.
- `subscription_country` is always `US`; `subscription_errors` identifies `US` for every error.

Deduplicate subscriptions by subscription ID, or by normalized service name when no ID is supplied. Preserve `leaving: null` as unknown. For duplicate records with different valid leaving dates, retain the earliest and mark coverage partial. Omit malformed or already-passed leaving records and mark coverage partial. Do not infer permanence from a null leaving date.

Subscription failures never suppress valid price, history, or bundle evidence. A successful empty result has no `subscription_reason` or `subscription_message` because its meaning is carried by the empty list and must not be narrated in the report.

## Epic giveaway interpretation

Query Epic Games Store history with `/games/history/v2`, `shops=16`, and `country=US`. Detect only explicit giveaway events where `deal.price.amount == 0` or `deal.cut == 100`.

Interpret the primary fields as follows:

- `epic_giveaway_status: available` means the exact lookup completed and any deterministic related-title fallback either completed, was unnecessary, or was skipped by rule. `epic_giveaway_detected: false` is not buyer-facing evidence and must not be narrated as absence.
- `epic_giveaway_status: partial` means exact lookup completed, but a required related-title fallback request failed. Preserve the reason and do not make absence claims.
- `epic_giveaway_status: unavailable` means the exact Epic history lookup failed or could not run. Preserve the reason and do not make giveaway claims.
- `epic_giveaway_scope: exact` means the direct Steam app ITAD identity, or the selected Steam-matched ITAD identity when no direct app identity exists, had the giveaway event.
- `epic_giveaway_scope: related_title` means a deterministic base-title fallback found the giveaway on a related ITAD game entry. State that this is related base-title evidence, not exact Steam SKU evidence.

Related-title fallback is deterministic only: use the English Steam AppDetails `name`, strip one allowed edition suffix, require exactly one exact-title ITAD game candidate, and require developer or publisher overlap from ITAD info. If any rule fails, omit the fallback without guessing.

When detected, show Epic giveaway context as a required `⚠️ Before you buy` notice and in the price table. It does not count toward the three material regret-risk limit.

Never suggest that a game may be given away again in the future.

## Shared request budget

Treat ITAD's 1,000 requests per rolling five minutes as one API-key budget across workers, wishlist handoffs, and concurrent runs. For each game estimate `6 + A` normal requests, where `A` is the number of distinct ITAD identities resolved from Steam app and package products: one product lookup, one Steam-filtered overview, one Steam store low, one Steam price history, one Epic giveaway history request, one US subscription request, and one bundle-history request per identity. Allow up to `A` additional active-bundle requests only when returned records or expiry data cannot determine availability, and up to three additional requests for deterministic related-title giveaway fallback. Regional Steam AppDetails identity validation does not consume ITAD quota. Include known prior consumption, reserve a safety margin, and never assign each worker a separate allowance.
