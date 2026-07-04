---
name: filter-steam-wishlist
description: List and filter a user's public Steam wishlist by current sale status, ITAD historical-low status, and pricing country, then resolve localized Steam titles using the report country. Accept a SteamID64, numeric Steam profile URL, custom Steam profile URL, or exact custom profile ID. Use when the user asks to list, show, find, or filter wishlist games; asks which wishlist games are on sale or at historical lows; or asks to analyze wishlist games before handing selected app IDs to the sibling evaluate-steam-games skill. Requires a resolvable Steam profile and public wishlist; gracefully returns the complete unfiltered wishlist when ITAD price data is unavailable.
---

# Filter Steam Wishlist

Select games from a public Steam wishlist, resolve localized titles, and hand selected app IDs to `evaluate-steam-games` only when analysis is requested. Do not check MCP readiness; this skill does not use the Steam Review and Forum MCP.

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
- Title resolver: `<repo-root>/.agents/lib/steam_purchase_advisor/resolve_steam_titles.py`
- User config: `<repo-root>/config.json`

At the start of every wishlist request, run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/config_status.py
```

The helper exposes only configuration presence, field errors, countries, and whether the ITAD key exists. Use it for identity, localization, and pricing decisions even in unfiltered mode. Never open `config.json` directly or print, quote, or expose `itad_api_key`. A Steam profile identifier or country supplied in the current request overrides config for that request only; never persist an override automatically.

## Guide first-use configuration

When `config.json` is absent or a relevant field is missing or invalid:

1. Explain in the user's language that the file is local and Git-ignored. Ask only for what the request needs:
   - `steam_id`: required unless this request supplies a SteamID64, a `/profiles/<SteamID64>` URL, an `/id/<custom-id>` URL, or an exact custom profile ID; the wishlist must be public.
   - `report_country`: required for title localization; use an uppercase ISO 3166-1 alpha-2 code and ask for a language when the country is multilingual.
   - `pricing_country`: required only for ITAD filtering.
   - `itad_api_key`: optional; without it, return the complete unfiltered wishlist and state that price filters were not applied.
2. Resolve request-supplied Steam identity input before discussing persistence. Store only the resolved 17-digit SteamID64, never the custom ID or URL.
3. Offer one combined confirmation to create or repair only the missing or invalid non-secret fields. Include `steam_id` only when `steam_id_configured` is false. If it is already configured, keep request-supplied identity input temporary and do not offer replacement unless the user explicitly asks to replace it.
4. After confirmation, use the bundled script's secret-safe update mode; pass the resolved numeric ID, not a custom ID or URL:

```text
python -B <skill-dir>/scripts/get_wishlist_appids.py --update-config-only [--steam-profile <STEAMID64>] [--report-country <CC>] [--country <CC>]
```

The update mode creates the standard shape when absent, preserves `itad_api_key` and unrelated settings internally, writes atomically, emits only status booleans and field names rather than configuration values, and refuses to replace valid existing fields. Use `--replace-existing` only after the user explicitly requests replacement and separately confirms the exact field names. Rerun the status helper after any update. If the user declines persistence, continue with request-only overrides and do not ask again during that request.

To obtain an ITAD key, direct the user to `https://isthereanydeal.com/apps/` to sign in, register an app, and edit the key into local config themselves. These scripts do not use the OAuth Client ID or Client Secret. Link `https://docs.isthereanydeal.com/` for API documentation. Never request the key in chat or on the command line; rerun the status helper afterward and report the key only as configured or not configured.

## Resolve the Steam profile and require a public wishlist

A resolvable Steam profile and public wishlist are mandatory.

- Accept a 17-digit SteamID64, `https://steamcommunity.com/profiles/<SteamID64>`, `https://steamcommunity.com/id/<custom-id>`, or an exact bare custom ID such as `your-custom-id`.
- Treat a bare nonnumeric value only as an exact custom profile ID, never as a display-name search.
- Pass request-supplied input to `--steam-profile`. The script extracts numeric profile URLs locally and resolves custom IDs through Steam Community, then validates the returned SteamID64.
- If no profile identifier is available, stop and explain the accepted forms in the user's language.
- If automatic resolution fails, explain the concise reason. Tell the user they may use `https://steamid.io/lookup/` to look up their custom ID or profile URL manually, then provide the resulting 17-digit SteamID64 in chat. Do not claim that `steamid.io` is affiliated with Valve.
- After resolving a request-supplied identifier, use the numeric ID for the current request. Follow the first-use rules above for any persistence decision.
- If the script returns `wishlist_unavailable`, stop and give its concise, non-sensitive reason.
- Treat a successful empty JSON array as an empty public wishlist.
- If Steam returns no usable items field, ask the user to verify the SteamID64 and wishlist visibility; do not report an empty wishlist.

## Select the wishlist mode

| Selection | Arguments |
| --- | --- |
| Generic "list/show my wishlist" request | `--no-on-sale-only` |
| Games currently on sale | none |
| Games at their historical low | `--historical-low-only` |
| Explicit complete-wishlist request | `--no-on-sale-only` |

Run:

```text
python -B <skill-dir>/scripts/get_wishlist_appids.py [--historical-low-only | --no-on-sale-only] [--steam-profile <STEAMID64-OR-PROFILE>] [--country <CC>]
```

`--steam-id` remains a backward-compatible alias for `--steam-profile`.

Map generic list and show requests to the complete wishlist. Apply a sale or historical-low filter only when the user explicitly requests it.

Parse successful stdout internally as a JSON array of numeric app IDs. For a list request, resolve and present titles as described below. For an analysis request, hand the selected IDs to `evaluate-steam-games`. Before handing off a complete unfiltered wishlist, report its size and ask the user to analyze all games or choose a subset.

## Resolve and present titles

For every non-empty result, run:

```text
python -B <repo-root>/.agents/lib/steam_purchase_advisor/resolve_steam_titles.py --appids <appid> [<appid> ...] [--report-country <CC>] [--language <steam-language>] [--max-workers <1-8>]
```

- Use the request or config `report_country`; ask for it when missing or invalid. For a multilingual country, ask for the report language and pass the matching Steam language with `--language`.
- Treat Steam's returned title as authoritative. Preserve the publisher's original title when Steam has no localization; never machine-translate it.
- Preserve result order. On an individual lookup failure, retain the game as linked `AppID <appid>`.
- Present successful results as linked localized titles with AppIDs. Do not return a bare AppID array when title resolution succeeds.
- Keep the resolver's default concurrency of four and maximum of eight. Lower it only for throttling or local constraints; retry only transient failures with backoff.

## Degrade when ITAD is unavailable

Price filtering requires `itad_api_key` and `pricing_country`.

- If the key is configured but the country is missing or invalid, ask for an uppercase two-letter country code and pass `--country <CC>`.
- If a filtered run returns `price_data_unavailable` because of a missing or invalid key, authentication or network failure, or rate limit, explain that current price, discount, and historical-low data are unavailable. Honor `Retry-After` once when practical.
- Rerun with `--no-on-sale-only` after an unresolved ITAD failure. If the user requested sale or historical-low filtering, state prominently that the filter was not applied and never describe the raw wishlist as filtered.
- Present list requests through the title resolver. Before handing an unfiltered fallback to `evaluate-steam-games`, report its size and require confirmation of all games or a subset.

## Preserve regional meaning and request limits

Treat country codes as regional price selectors, not currency codes. Never convert currencies or apply one country's result to another.

Treat ITAD's 1,000 requests per rolling five minutes as one shared API-key budget. Estimate this script's upper bound as `2 * ceil(wishlist app IDs / 200)` requests; unfiltered mode uses none. Reserve a safety margin, honor rate limits, and pass known consumption to `evaluate-steam-games` on handoff.
