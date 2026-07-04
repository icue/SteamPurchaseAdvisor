# Steam Purchase Advisor

[简体中文](README.zh-CN.md)

Steam Purchase Advisor is a Skills bundle for filtering public Steam wishlists and evaluating games before purchase.

## Included skills

| Skill | Purpose |
| --- | --- |
| [filter-steam-wishlist](.agents/skills/filter-steam-wishlist/SKILL.md) | Lists a public wishlist, optionally filters it by sale, historical-low, Early Access, or full-release status. |
| [evaluate-steam-games](.agents/skills/evaluate-steam-games/SKILL.md) | Produces reports from Steam reviews, recent forum activity, current product health, and Early Access development signals. |

## Example prompts

- “List my Steam wishlist.”
- “Show my wishlisted games currently matching or beating their historical low.”
- “Show my Early Access wishlist games currently on sale.”
- “Show all fully released games on my wishlist.”
- “Should I buy Steam game XXX now?”
- “Evaluate all my wishlisted games currently on sale.”

## Requirements

- An Agent Skills-compatible client and Python 3.
- A public Steam wishlist. For wishlist filtering, provide a SteamID64, numeric or custom Steam profile URL, or exact custom profile ID.
- [Node.js 22.19+](https://nodejs.org/) with npm/npx for the evaluator's [Steam Review and Forum MCP](https://github.com/icue/SteamReviewAndForumMcp).
- An [IsThereAnyDeal API key](https://isthereanydeal.com/apps/) only if price, discount, or historical-low data is needed.

## Quick start

1. Clone or download this repository and make its **.agents/skills/** directory available to your Agent Skills-compatible client.
2. Start either workflow directly:

   - **Wishlist filtering:** ask to list or filter your wishlist and provide a SteamID64, numeric profile URL, custom profile URL, or exact custom profile ID when `steam_id` is not already configured.
   - **Game evaluation:** ask whether to buy one or more games using their names, AppIDs, or Steam Store URLs.

For game evaluation, if the Steam Review and Forum MCP is unavailable, the skill asks once for permission and attempts to register it using the client's current official configuration mechanism.

If automatic registration is unavailable or fails, manually register this stdio server in the client:

- Server name: `steam-review-and-forum`
- Command: `npx`
- Arguments: `-y`, `steam-review-and-forum-mcp`

A common JSON representation is:

```json
{
  "mcpServers": {
    "steam-review-and-forum": {
      "command": "npx",
      "args": ["-y", "steam-review-and-forum-mcp"]
    }
  }
}
```

The exact configuration schema and location depend on the client; follow its current official MCP documentation. Refresh or restart it after changing the configuration.

## Configuration

Every value in **config.json** is a JSON string and must keep its double quotes. An empty string (**""**) means not configured. See [config.example.json](config.example.json) for the exact shape.

| Field | Format and capability |
| --- | --- |
| **steam_id** | A 17-digit SteamID64 string. Enables public-wishlist operations. |
| **itad_api_key** | An ITAD API-key string. Enables current prices, discounts, and historical-low checks. Create an app at [IsThereAnyDeal](https://isthereanydeal.com/apps/) to obtain one. |
| **pricing_country** | Uppercase two-letter ISO 3166-1 country code, such as **"US"** or **"CN"**. Selects regional price data. |
| **report_country** | Uppercase two-letter ISO 3166-1 country code. Selects language for report and Steam title localization. |

Request-time profile URLs and custom IDs are resolved automatically. Only canonical 17-digit SteamID64 values are stored in **config.json**.

**config.json** is Git-ignored. Never commit it, publish its API key, paste the key into chat, or pass it on a command line.

## License

[BSD 3-Clause](LICENSE)
