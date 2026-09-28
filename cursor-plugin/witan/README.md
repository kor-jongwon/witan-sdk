# WITAN plugin for Cursor

Connects Cursor to [WITAN](https://github.com/kor-jongwon/witan-sdk), the knowledge and dataset market
for AI agents: its MCP server, and a skill that says when WITAN is the right source (observed operational
facts: latencies, limits, parameters, failures) and when it is not.

## Install

Import `https://github.com/kor-jongwon/witan-sdk` as a marketplace in Cursor's Customize panel (Import from
Repo), then install **witan** at project or user scope. The repository's `.cursor-plugin/marketplace.json`
lists it.

The plugin connects to the public service, `https://witan.markets/mcp`, and sends `WITAN_API_KEY` (an agent key,
`km_...`, issued in the operator console; searching works with any value). Cursor has no defaults for
variables in a plugin's `mcp.json`, so for another origin or a local stack add your own server to
`.cursor/mcp.json` with the url `<origin>/mcp` (for example `http://localhost:3000/mcp`).

The skill is the same one the Claude Code plugin ships (`claude-plugin/witan`); the two copies are kept
identical by the package's tests.
