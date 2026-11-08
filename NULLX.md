# nullx

A terminal coding agent built in Go, designed after Crush's architecture and
backed by the [opencode2api](https://github.com/jasonxu114514/opencode2api)
gateway for "unlimited" free-tier model access through rotation aliases.

`nullx` is a single static binary with no external dependencies. It speaks the
OpenAI Chat Completions protocol, so any OpenAI-compatible gateway works, and
ships with first-class support for the opencode2api rotation groups (`sota` /
`sweet`), key pools, proxy rotation, and WARP egress.

> Status: v0.1.0 — agent loop, streaming, tools, permissions, sessions, and the
> gateway launcher are complete. The Bubble Tea TUI, LSP, and MCP are the next
> layers (see Roadmap).

## Why this exists

Crush is a mature, beautiful TUI agent. This project borrows its *shape* — a
config service, a coordinator/agent loop, self-documenting tools, a system
prompt with context files, and persisted sessions — while staying deliberately
small and dependency-free so it builds anywhere with a Go toolchain.

The pairing with opencode2api is the point: the gateway handles provider
translation, key/proxy pools, retries, health checks, and free-model rotation.
`nullx` stays a thin, fast client.

## Requirements

- Go 1.24 or newer (only to build; the binary is standalone).
- A running opencode2api gateway, or any OpenAI-compatible endpoint.

## Install

One command installs the gateway and `nullx` together:

```bash
curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/install.sh | bash
nullx
```

From a clone:

```bash
git clone https://github.com/Inkflow-Gab/nullxOpenS.git
cd nullxOpenS
bash install.sh
```

Then:

```bash
nullx                     # interactive shell
nullx "explain this repo" # one-shot prompt
nullx models -free        # list free models
nullx doctor              # gateway + free-model check
opencode-proxy status     # gateway control
```

`nullx` auto-reads the first `server_keys` entry from
`~/.opencode-proxy/config.json` and finds `~/.opencode-proxy/bin/opencode2api`,
so no API key needs to be copied by hand.

## Manual setup (developers)

1. Start the gateway:

   ```bash
   cp config.example.json config.json
   # set server_keys, optional zen_keys/go_keys, and webui.password
   cd /path/to/opencode2api
   go build -o opencode2api ./cmd/opencode2api
   ./opencode2api -config config.json
   ```

2. Build `nullx` and write a config:

   ```bash
   cd nullxOpenS
   CGO_ENABLED=0 go build -trimpath -o nullx .
   ./nullx init
   ```

   Minimum settings in `~/.config/nullx/config.json`:

   ```json
   {
     "base_url": "http://127.0.0.1:8080/v1",
     "api_key": "local-test-key",
     "model": "auto"
   }
   ```

`model: "auto"` (the default) asks the gateway for `/v1/models` and picks a free
model, preferring the OpenCode UNLIMITED order (`deepseek-v4.1-flash-free`
first). That is what makes the anonymous lane work out of the box.

## Free models and the "unlimited" setup

opencode2api marks a model free-tier when its ID contains `free` or its pricing
metadata lists zero input and output cost. With `anonymous: true`, a free model
is served through the keyless lane using the OpenCode `public` credential, over
your configured proxies or WARP.

`nullx` defaults to `model: "auto"`. On startup it calls `/v1/models` and picks
the first advertised model from its preferred free list, then any free model
that supports tool calls. Use `nullx doctor` to verify the whole path and
`nullx models -free` to see the candidates.

opencode2api also exposes two rotation aliases that walk a group of models and
fail over on quota, rate limit, or upstream failure:

- `sota` — the stronger models (default order: `deepseek-v4.1-flash`, `glm-5.3`,
  `grok-4.6`, `kimi-k3`, `qwen3.8-max`).
- `sweet` — whatever you put in `rotation.sweet.order`.

Rotation aliases are routed through the **Go** key tier in opencode2api, so they
only appear in `/v1/models` when at least one Go key is configured. For pure
free-tier access, use the free model IDs directly (or leave `model` on `auto`).

Switch models at runtime with `/model <id>` or by passing `-model`. If you want a
specific free model, set `"model"` to its catalog ID. If you want the Go
rotation, set `"model": "sota"` and configure a Go key in the gateway.

## Commands

| Command | Purpose |
| --- | --- |
| `nullx` | Interactive shell (REPL). |
| `nullx run "prompt"` | One prompt, one answer, exit. |
| `nullx models [-free]` | List gateway model IDs, context windows, and free markers. |
| `nullx doctor` | Check the gateway, credentials, and free-model availability. |
| `nullx init [-force]` | Write the default config. |
| `nullx config` | Print the config path and masked values. |
| `nullx sessions` | List persisted sessions. |
| `nullx tools` | List the built-in tools. |
| `nullx gateway [-bin PATH] [-config PATH]` | Run the opencode2api binary. |
| `nullx version` | Print the version. |

Shell commands:

| Command | Purpose |
| --- | --- |
| `/exit`, `/quit` | Leave the shell. |
| `/clear` | Reset the conversation and the saved session. |
| `/model <id>` | Change the model for this session. |
| `/tools` | Show the registered tools. |
| `/session` | Show the session ID and message count. |
| `/config` | Show the active configuration (key masked). |
| `/help` | Show command help. |

## Configuration

Config path: `$NULLX_CONFIG`, or `<user-config-dir>/nullx/config.json`
(usually `~/.config/nullx/config.json` on Linux,
`~/Library/Application Support/nullx/config.json` on macOS, and
`%AppData%\nullx\config.json` on Windows).

| Field | Default | Meaning |
| --- | --- | --- |
| `base_url` | `http://127.0.0.1:8080/v1` | OpenAI-compatible base URL. |
| `api_key` | auto-detected local key | Sent as `Authorization: Bearer`; falls back to the installed gateway's `server_keys`. |
| `model` | `auto` | Model ID, `auto` (preferred free model), or a rotation alias. |
| `system_prompt` | empty | Extra instructions appended to the built-in prompt. |
| `max_tokens` | `8192` | Per-completion token ceiling. |
| `temperature` | `0.2` | Sampling temperature. |
| `max_steps` | `40` | Tool-call loop ceiling. |
| `timeout_seconds` | `300` | HTTP request timeout. |
| `permission` | `ask` | `ask`, `allow`, or `deny` for tool execution. |
| `context_files` | `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, `NULLX.md`, `.nullx.md` | Project instruction files. |
| `gateway_bin` | auto-detected | `~/.opencode-proxy/bin/opencode2api` when installed, otherwise `opencode2api` on `PATH`. |
| `gateway_config` | auto-detected | `~/.opencode-proxy/config.json` when present, otherwise `config.json`. |

Environment overrides (highest precedence for the connection fields):

- `NULLX_CONFIG`, `NULLX_DATA`
- `NULLX_BASE_URL`, `NULLX_API_KEY`, `NULLX_MODEL`
- `NULLX_GATEWAY_BIN`, `NULLX_GATEWAY_CONFIG`

`NULLX_API_KEY` always wins over the key read from the gateway config.

## Tools

Each tool has a JSON schema and a description, mirroring Crush's
self-documenting tool pattern.

| Tool | Behavior |
| --- | --- |
| `read` | Read a file with line numbers. Supports `offset` and `limit`. |
| `write` | Create or overwrite a file, creating parent directories. |
| `edit` | Replace the first exact occurrence of `old` with `new`. |
| `ls` | List a directory. |
| `bash` | Run a shell command with a timeout; returns combined output. |
| `glob` | Find files with `*`, `?`, and `**` segments. |
| `grep` | Regex content search with an optional include glob. |

Official OpenCode tool names are aliased at execution time (`shell` / `bash` →
`bash`, `view` → `read`, `patch` → `edit`, `find` → `glob`, `search` → `grep`),
and the edit tool accepts both `path`/`old`/`new` and the official
`filePath`/`oldString`/`newString`/`replaceAll` fields. This matters on the
anonymous lane: the gateway shapes the request into an official CLI session and
appends the official tool set, so the model may answer with an official name.
`patch` currently expects `path`/`old`/`new`; a `patchText`-only call returns an
instructional error and the model can retry with `edit` or `write`.

Safety bounds: reads cap at 1 MiB, grep files at 2 MiB, command output at
64 KiB, glob results at 1000, and grep matches at 500. `bash` defaults to a
120-second timeout.

## Permissions

`permission: "ask"` (default) asks before every tool call when stdin is a
terminal, and denies when it is not (piped or scripted runs). Use `"allow"` for
unattended runs and `"deny"` to add a hard stop. The gate runs before the tool,
not inside it.

## Troubleshooting free models

Run `nullx doctor`. It prints:

- whether `/healthz` answers and what `status`/`ready` say;
- how many Zen, Go, and anonymous credentials the gateway reports;
- the total and free model count from `/v1/models`;
- the model `auto` would select.

If `models: N total, 0 free`, the gateway is not advertising a free model. Check
that `anonymous: true` is set, that the model catalog has refreshed, and that
`models.free_only` is not hiding everything. If health reports
`no_healthy_proxies`, fix the proxy list (or enable WARP); the keyless lane needs
a route to the upstream.

If a request fails with a model error, `nullx` refreshes the catalog and retries
once with the preferred free model automatically.

## Sessions

Conversations are written to `<data-dir>/sessions/<id>.json` after every
message and tool result, atomically (temp file + rename). `nullx sessions`
lists them. This is deliberately simpler than Crush's SQLite layer; the model
is the same message stream, so a SQLite backend can replace the store later
without touching the agent loop.

## Design map (Crush → nullx)

| Crush | nullx |
| --- | --- |
| `main.go` + `internal/cmd` (cobra) | `main.go` + `internal/cmd` (stdlib `flag`) |
| `internal/config` (config service) | `internal/config` |
| `internal/agent` (`SessionAgent`) | `internal/agent` |
| `internal/agent/tools` | `internal/tools` |
| `internal/agent/templates` (Go templates) | `internal/agent/prompt.go` |
| `charm.land/fantasy` (providers) | `internal/llm` (OpenAI-compatible client) |
| Bubble Tea TUI | line REPL (`internal/ui` + `internal/cmd/repl`) |
| SQLite + sqlc sessions | JSON session store |
| Hooks, permissions, LSP, MCP | permissions now; hooks/LSP/MCP on the roadmap |

The gateway replaces the provider abstraction on purpose: opencode2api already
normalizes Anthropic, OpenAI, and Responses, so `nullx` only needs one wire
protocol and still reaches every model the gateway routes.

## Roadmap

- Bubble Tea TUI with split panes and a status bar.
- LSP client for diagnostics and code intelligence.
- MCP server support.
- SQLite session store with search.
- Hooks before tool execution.
- Image and file attachments.
- Multiple saved provider profiles.

## Security notes

- The config can hold an API key; `nullx` writes it with mode `0600` and masks
  it in `nullx config`.
- `bash` executes model-chosen commands with your privileges. Keep
  `permission: "ask"` unless you trust the workload.
- The gateway's WebUI is separate; bind it to loopback and change its password.
