---
name: filter-steam-wishlist
description: List and filter a user's public Steam wishlist by current Steam Store sale status, Steam Store historical-low status, Steam Early Access or full-release state, and pricing country, then resolve localized Steam titles using the report country. Accept a SteamID64, numeric Steam profile URL, custom Steam profile URL, or exact custom profile ID. Use when the user asks to list, show, find, or filter wishlist games; asks which wishlist games are on sale, at historical lows, in Early Access, or fully released; or asks to analyze wishlist games before handing selected app IDs to the sibling evaluate-steam-games skill. Requires a resolvable Steam profile and public wishlist; gracefully preserves requested non-price filters when ITAD price data is unavailable.
---

# Filter Steam Wishlist

Select games from a public Steam wishlist, localize titles, and hand IDs to `evaluate-steam-games` only for analysis. Do not check MCP readiness; this skill does not use that server. Price filtering covers only the Steam Store, excluding third-party key sellers.

## Protect repository state during execution

- Treat the repository as read-only except when creating or updating `config.json` after explicit user confirmation.
- Never modify an existing Python file or create helper scripts in the repository. Report bundled-script failures instead.
- Keep temporary state outside the repository. If repository-local state is unavoidable, use one uniquely named, tracked path; remove it on success, failure, or cancellation after verifying the cleanup target and report any residue.
- Run bundled scripts with Python 3 and `-B`. Do not install dependencies into the repository.

## Resolve paths and configuration

Resolve paths relative to this `SKILL.md`:

- Wishlist script: `scripts/get_wishlist_appids.py`
- Repository root: three directories above this skill directory
- Config status helper: `<repo-root>/.agents/lib/steam_purchase_advisor/config_status.py`
- Config update helper: `<repo-root>/.agents/lib/steam_purchase_advisor/update_config.py`
- Steam identity helper: `<repo-root>/.agents/lib/steam_purchase_advisor/steam_identity.py`
- Title resolver: `<repo-root>/.agents/lib/steam_purchase_advisor/resolve_steam_titles.py`
- User config: `<repo-root>/config.json`

At the start of every wishlist request, run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/config_status.py
```

The helper exposes only configuration presence, field errors, countries, and whether the ITAD key exists. Use it even in unfiltered mode. When all required fields are valid, stay silent about configuration and do not run the update helper. Never open `config.json` or expose `itad_api_key`. Request-supplied profile or country values override config only for that request; never persist them automatically.

## Guide first-use configuration

When `config.json` is absent or a relevant field is missing or invalid:

1. Explain in the user's language that the file is local and Git-ignored. Ask only for what the request needs:
   - `steam_id`: required unless this request supplies a SteamID64, a `/profiles/<SteamID64>` URL, an `/id/<custom-id>` URL, or an exact custom profile ID; the wishlist must be public.
   - `report_country`: required for title localization; use an uppercase ISO 3166-1 alpha-2 code and ask for a language when the country is multilingual.
   - `pricing_country`: required only for ITAD filtering.
   - `itad_api_key`: optional; without it, price filters are unavailable. Return the complete price-unfiltered wishlist while preserving any explicit release-state filter, and state that price filtering was not applied.
2. Resolve request-supplied Steam identity input before discussing persistence:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/steam_identity.py --steam-profile <STEAMID64-OR-PROFILE>
```

   Use the returned `steam_id` for the request and any save offer. Store only the resolved 17-digit SteamID64, never the custom ID or URL.
3. Offer one combined confirmation to create or repair only the missing or invalid non-secret fields. Include `steam_id` only when `steam_id_configured` is false. If it is already configured, keep request-supplied identity input temporary and do not offer replacement unless the user explicitly asks to replace it.
4. After confirmation, use the shared secret-safe update helper; pass the resolved numeric ID, not a custom ID or URL:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/update_config.py [--steam-id <STEAMID64>] [--report-country <CC>] [--pricing-country <CC>]
```

The helper atomically creates the standard shape, preserves `itad_api_key` and unrelated settings, emits no values, and refuses to replace valid fields. Use `--replace-existing` only after the user requests replacement and separately confirms exact field names. Rerun status after updates. If persistence is declined, use request-only overrides without asking again.

For an ITAD key, direct the user to `https://isthereanydeal.com/apps/` to register an app and edit local config. The scripts ignore OAuth Client ID and Client Secret; link `https://docs.isthereanydeal.com/` for API documentation. Never request the key in chat or CLI. Rerun status and report only configured or not configured.

## Resolve the Steam profile and require a public wishlist

- Accept a 17-digit SteamID64, `https://steamcommunity.com/profiles/<SteamID64>`, `https://steamcommunity.com/id/<custom-id>`, or an exact bare custom ID such as `your-custom-id`.
- Treat a bare nonnumeric value only as an exact custom profile ID, never as a display-name search.
- Pass request-supplied input to `--steam-profile`. The script extracts numeric profile URLs locally and resolves custom IDs through Steam Community, then validates the returned SteamID64.
- If no profile identifier is available, stop and explain the accepted forms in the user's language.
- If resolution fails, give the concise reason and offer `https://steamid.io/lookup/` for manual lookup, followed by the resulting SteamID64 in chat. Do not imply Valve affiliation.
- After resolving a request-supplied identifier, use the numeric ID for the current request. Follow the first-use rules above for any persistence decision.
- If the script returns `wishlist_unavailable`, stop and give its concise, non-sensitive reason.
- Treat a successful empty JSON array as an empty public wishlist.
- If Steam returns no usable items field, ask the user to verify the SteamID64 and wishlist visibility; do not report an empty wishlist.

## Select filters

Map price intent independently:

| Price intent | Argument |
| --- | --- |
| Generic list/show or explicit complete wishlist | `--no-on-sale-only` |
| Currently on sale | none |
| At the Steam Store historical low | `--historical-low-only` |

Map release intent independently:

| Release intent | Argument |
| --- | --- |
| Not specified | default `--release-state any` |
| Early Access | `--release-state early-access` |
| Full release | `--release-state full-release` |

Run:

```text
python -B <skill-dir>/scripts/get_wishlist_appids.py [--historical-low-only | --no-on-sale-only] [--release-state any|early-access|full-release] [--steam-profile <STEAMID64-OR-PROFILE>] [--country <CC>]
```

`--steam-id` remains a backward-compatible alias for `--steam-profile`.

Apply only explicitly requested filters and combine the selected price and release arguments.

Sale and historical-low filters restrict results to Steam Store deals (`shop_id=61`, `vouchers=false`). The `--historical-low-only` flag compares each Steam deal's current price against its per-store low, not a cross-store historical low.

For price filtering, pass `pricing_country` to Steam AppDetails as `cc`; never pass a currency or perform conversion. The script uses bounded retries and at most four concurrent requests. It exact-matches Steam currency and initial/final minor-unit amounts against ITAD, preferring `app/<appid>` and accepting base-price packages only when they resolve unambiguously to one identity. It omits ambiguous or unmatched products and never selects by response order or title.

Missing `price_overview` means unpriced and not on sale; a complete undiscounted price is also not on sale. Malformed currency or minor-unit amounts produce `price_data_unavailable` with reason `steam_price_metadata_malformed` and no partial price-filtered result.

The script then applies release-state filtering while preserving wishlist order: genre ID `70` means Early Access, non-coming-soon without ID `70` means full release, and coming-soon matches neither. An unclassifiable candidate produces `release_state_data_unavailable` with no partial result; stop and report that the filter could not be applied.

Parse successful stdout internally as a JSON array of numeric app IDs. Resolve titles for list requests; hand selected IDs to `evaluate-steam-games` for analysis. Before handing off any complete price-unfiltered wishlist, including a fallback, report its size and require confirmation of all games or a subset.

## Resolve and present titles

For every non-empty result, run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/resolve_steam_titles.py --appids <appid> [<appid> ...] [--report-country <CC>] [--language <steam-language>] [--max-workers <1-8>]
```

- Use the request or config `report_country`; ask for it when missing or invalid. For a multilingual country, ask for the report language and pass the matching Steam language with `--language`.
- Treat Steam's returned title as authoritative. Preserve the publisher's original title when Steam has no localization; never machine-translate it.
- Preserve result order. On an individual lookup failure, retain the game as linked `AppID <appid>`.
- Present successful results as linked localized titles with AppIDs. Do not return a bare AppID array when title resolution succeeds.
- Keep the resolver's default concurrency of four and maximum of eight; lower it only for throttling or local constraints. Its retry policy is code-enforced. Preserve specific failures, including `steam_title_not_returned` and `steam_invalid_response`.

## Degrade when ITAD is unavailable

Price filtering requires `itad_api_key` and `pricing_country`.

- If the key is configured but the country is missing or invalid, ask for an uppercase two-letter country code and pass `--country <CC>`.
- If a filtered run returns `price_data_unavailable` because of a missing or invalid key, ITAD authentication or network failure, Steam AppDetails failure, or rate limit, explain that current price, discount, and historical-low data are unavailable. Honor `Retry-After` once when practical.
- Rerun with `--no-on-sale-only` after an unresolved ITAD failure, preserving any explicit `--release-state` selection. If the user requested sale or historical-low filtering, state prominently that the price filter was not applied and never describe the fallback as price-filtered.
- Present fallback list requests through the title resolver.

Release-state filtering uses Steam Store metadata independently of ITAD. When it returns `release_state_data_unavailable`, do not rerun without `--release-state`, do not treat unknown metadata as full release, and do not present a partial release-state result.

## Preserve regional meaning and request limits

Treat country codes as regional price selectors, not currency codes. Never convert currencies or apply one country's result to another.

Treat ITAD's 1,000 requests per rolling five minutes as one shared API-key budget. Let `P` be the number of distinct app and eligible base-package products discovered for wishlist games that Steam reports as discounted. Estimate this script's upper bound as `2 * ceil(P / 200)` ITAD requests: one product-lookup pass and one price pass; unfiltered mode uses none. Reserve a safety margin, honor rate limits, and pass known consumption to `evaluate-steam-games` on handoff.

Price filtering uses one regional Steam Store AppDetails request per wishlist item. When release-state filtering is also requested, expect one additional AppDetails request per candidate remaining after price filtering. The script uses at most four concurrent Store requests and bounded retries. Release-state-only requests do not require an ITAD key or `pricing_country`.
