# Pricing and bundle contract

Read this file completely before running `historical_low_checker.py` or interpreting its output.

## Contents

- Regional identity and scope
- Independent evidence statuses
- Report field mappings and timing judgments
- Bundle interpretation
- Shared request budget

## Regional identity and scope

Use `pricing_country` for Steam AppDetails `cc` and ITAD regional prices. Do not pass a currency. Preserve every amount and ISO currency exactly and never perform FX conversion.

Standalone price, sale, and historical-low analysis is Steam Store-only (`price_scope: "steam"`). Bundles are the explicit multi-store exception.

The script resolves the Steam app and associated Steam packages in one ITAD lookup. Require the current Steam offer to match regional Steam AppDetails currency plus initial and final minor-unit amounts exactly. Prefer the matching app identity. Only when it does not match, accept a base-price package from Steam purchase options. Accept multiple matching packages only when they resolve to one ITAD identity; otherwise mark standalone pricing ambiguous. Never choose by response order or title.

Query store low and history for the exactly matched identity, or the sole distinct identity when current overview is unavailable. When multiple identities remain without an exact match, mark low and history unavailable rather than guessing. Query bundle history for every distinct resolved identity and deduplicate by ITAD bundle ID.

## Independent evidence statuses

- When `price_status` is `available`, use `current_price`; `regular_price` and `discount_percent` may independently be null.
- When `price_status` is `unavailable`, preserve `reason`, mark current price, regular price, and discount unavailable, and continue. If exactly one identity was resolved, current-overview failure does not suppress a valid Steam low or history result.
- Use `historical_low_price` only when `steam_low_status` is `available`; use `steam_low_timestamp` as its date. Compare it with current price only when `steam_low_comparison_status` is `available`.
- Preserve `steam_low_reason`, `steam_low_message`, and `steam_low_retry_after` when the low is unavailable. Preserve `steam_low_comparison_reason` and `steam_low_comparison_message` when comparison fails. Use `current_price_unavailable` when a low exists without current price.
- After product lookup and unambiguous identity resolution, current price, Steam low, low comparison, Steam history, and bundles fail independently. A shared ITAD rate limit or unresolved identity may suppress dependent signals.
- For `itad_rate_limited`, honor `retry_after` when practical and retry once. Treat other ITAD failures as non-fatal. Never invent missing price evidence.

## Report field mappings and timing judgments

Map buyer-facing fields exactly:

| Report field | Script field and null behavior |
|---|---|
| Now | `current_price`; otherwise Unavailable |
| Regular price | `regular_price`; otherwise Unavailable |
| Discount | `discount_percent`; otherwise Unavailable |
| Steam recorded low | `historical_low_price` with `steam_low_timestamp`; otherwise Unavailable |
| Compared with recorded low | `steam_low_comparison_status`; equal = Matches, lower = Establishes a new low, higher = Above, otherwise Unavailable |
| Exact-low recurrence | `exact_low_pattern`; map explicit `insufficient` to Insufficient and null to Unavailable |
| Recurring realistic sale level | `recurring_sale_price`; map null to None found only when Steam history and regular price are available, otherwise Unavailable |
| Sustained list-price change | `list_price_change`; map explicit types to matching states and null to Unavailable |

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

## Shared request budget

Treat ITAD's 1,000 requests per rolling five minutes as one API-key budget across workers, wishlist handoffs, and concurrent runs. For each game estimate `4 + A` normal requests, where `A` is the number of distinct ITAD identities resolved from Steam app and package products: one product lookup, one Steam-filtered overview, one Steam store low, one Steam price history, and one bundle-history request per identity. Allow up to `A` additional active-bundle requests only for missing or malformed expiry values. Regional Steam AppDetails identity validation does not consume ITAD quota. Include known prior consumption, reserve a safety margin, and never assign each worker a separate allowance.
