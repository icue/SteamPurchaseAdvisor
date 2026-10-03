# Steam Review and Forum MCP setup

Read and follow this procedure only when the readiness gate in `SKILL.md` cannot verify the required server version, finds a missing required tool, or encounters a probe failure because of transport, connection, or timeout. The minimum version is defined in that gate.

For an already connected server that reports an older version or cannot provide a valid version, explain the observed version or verification failure and required minimum, and ask the user to update their MCP installation and reconnect. Keep evaluation stopped until the readiness gate passes. Do not register another server or change configuration solely because the running version is outdated or unverified.

Use the registration steps below for missing tools or connection failures that require setup.

1. Ask once for permission to register and run the MCP. Explain that this may require a minimal edit to the current client's documented personal MCP configuration outside the repository when dynamic registration is unavailable. Prefer the narrowest non-repository scope. Treat approval as authorization only for that server-entry change; require separate explicit approval for project or workspace configuration.
2. After approval, verify that the client can resolve `npx`. Never install Node.js, npm, or npx automatically. If unavailable, explain that Node.js 22.19+ with npm is required and stop.
3. Prefer supported dynamic stdio registration. Register server name `steam-review-and-forum`, command `npx`, and ordered arguments `-y`, `steam-review-and-forum-mcp`; do not pin a version.
4. If dynamic registration is unavailable or fails, identify the active client and version when possible. Consult current official vendor documentation for its registration command or configuration location, schema, scope, and reload requirements. Prefer an official URL supplied by the user or client; otherwise search only vendor-owned documentation. Never rely on blogs, forums, snippets, remembered paths, or another client's schema. If official guidance is unavailable, conflicting, or ambiguous, do not guess.
5. Translate the server specification into the documented schema. Preserve unrelated settings, never print the full configuration or credentials, and make only the authorized server-entry change. Validate with a parser or native facility when available.
6. Explain any documented refresh or restart requirement after a persistent change, and reconnect after updating the server to reload its tool definitions. Repeat the readiness gate in `SKILL.md`, including its required `get_server_info` version check; continue only when the version meets the minimum and the metadata probe is available.
7. Give manual registration instructions only when the client cannot be identified, official documentation cannot establish a safe mechanism, configuration cannot be safely located or written, or both dynamic and documented registration fail. If the user declines or readiness remains unavailable, stop without review preflight, ITAD queries, corpus creation, per-game workers, or a report.

The MCP client must own the stdio process; never merely launch `npx` in a shell.
