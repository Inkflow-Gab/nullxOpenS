# OpenCode UNLIMITED

OpenCode Unlimited on Android (Termux) — rotating Cloudflare WARP egress pool for unlimited free OpenCode models. No root, no Docker, no external servers.

<p align="center">
  <img src="https://img.shields.io/badge/platform-Android%20%7C%20Termux%20ARM64-green?style=for-the-badge" alt="platform">
  <img src="https://img.shields.io/badge/engine-opencode2api%20v1.4.6-blue?style=for-the-badge" alt="engine">
  <img src="https://img.shields.io/badge/opencode-v1.19.5-purple?style=for-the-badge" alt="opencode">
  <img src="https://img.shields.io/badge/license-MIT-red?style=for-the-badge" alt="license">
</p>

---

## About

OpenCode UNLIMITED is an all-in-one Python setup that installs and manages the `opencode2api` gateway plus the OpenCode CLI. It rotates through Cloudflare WARP IPv6 exits to eliminate per-IP rate limits on the anonymous free tier — giving you unlimited access to OpenCode's free models.

Works on native Termux **and** inside `proot-distro login ubuntu` — it auto-detects `pkg` vs `apt` and skips Termux-only packages when not on Termux.

Built and maintained by **null**.

---

## Features

- One-command setup via `setup.py` (Termux + Ubuntu/proot-distro)
- `opencode2api` v1.4.6 gateway with WARP IPv6 egress rotation
- OpenCode CLI v1.19.5 via `glibc-runner` (`grun`)
- Double-fork daemon spawner — survives terminal close
- OpenAI-compatible `/v1` endpoint at `http://127.0.0.1:8080/v1`
- Web dashboard at `http://127.0.0.1:8081`
- 10 verified free-tier models exposed
- No Docker, no root, no external server required

---

## Quick Start

One command (works on Termux and proot-distro Ubuntu):

```bash
curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3
```

Or clone and run locally:

```bash
git clone https://github.com/Inkflow-Gab/nullxOpenS.git
cd nullxOpenS
python3 setup.py install
```

Once installed:

```bash
opencode-unlimited start    # starts proxy + launches CLI together
opencode-unlimited status   # check both proxy and CLI
opencode-unlimited stop     # stop everything
```

Or use them separately:

```bash
opencode-proxy start
opencode-proxy status
opencode
```

---

## Commands

| Command | Description |
|---------|-------------|
| `python3 setup.py install` | Full one-command setup |
| `opencode-proxy start` | Start the proxy daemon |
| `opencode-proxy stop` | Stop the proxy daemon |
| `opencode-proxy restart` | Restart the proxy daemon |
| `opencode-proxy status` | Check daemon + WARP + model status |
| `opencode-proxy test [model]` | Send a test chat request |
| `opencode-proxy logs` | Stream recent proxy logs |
| `opencode` | Launch OpenCode CLI TUI |
| `opencode-unlimited start` | Start proxy + launch CLI together |
| `opencode-unlimited stop` | Stop proxy + CLI |
| `opencode-unlimited restart` | Restart proxy + CLI |
| `opencode-unlimited status` | Check both proxy and CLI |
| `opencode-proxy skills list` | List installed skills |
| `opencode-proxy skills install` | Install built-in skills (web-design, frontend-dev, backend-dev, fullstack-dev, debugging, code-review, api-design, sql-database) |
| `opencode-proxy skills show <name>` | Show skill details & system prompt |
| `opencode-proxy skills add <name>` | Create a custom skill |
| `opencode-proxy skills remove <name>` | Remove a skill |
| `opencode-proxy models list` | List all detected free models with rankings |
| `opencode-proxy models best` | Show top 3 free models |

---

## Architecture

```
Android Device (Termux / Ubuntu proot-distro)
├── OpenCode CLI (TUI)          -> grun -> opencode-bin
│      └── HTTP 127.0.0.1:8080/v1
├── opencode2api Gateway        -> chroot -> WARP IPv6 pool
│      ├── rotating egress on 429/403
│      └── web dashboard :8081
└── Outbound WireGuard UDP (2408)
      -> Cloudflare Edge
      -> Rotated egress /64 block
      -> OpenCode Free-Tier Inference
```

---

## Models Exposed

| Model | Use Case | Context |
|-------|----------|---------|
| `deepseek-v4.1-flash-free` | Code, algorithms, refactoring | 128K |
| `big-pickle` | Multi-step reasoning, planning | 200K |
| `crouton-alpha-free` | Massive context, multimodal docs | 1M |
| `nemotron-3.5-super-vl-free` | Vision-language tasks | 1M |
| `nemotron-3.5-lightning-free` | Low-latency scripts, commands | 262K |
| `glm-5.3-flash-free` | General knowledge | 128K |
| `beam-free` | Step-by-step logic | 1M |
| `mimo-v2.6-flash-free` | Compact quick assistant | 128K |
| `flint-40b-free` | Open-weight foundation | 128K |
| `pulse-alpha-free` | Multimodal input | 1M |

---

## Skills

OpenCode UNLIMITED includes built-in **skills** — pre-configured system prompts for specific tasks. Install them with:

```bash
opencode-proxy skills install
```

Then view or add them:

```bash
opencode-proxy skills list
opencode-proxy skills show web-design
opencode-proxy skills add my-skill
```

### Built-in Skills

| Skill | Category | Description |
|-------|----------|-------------|
| `web-design` | design | UI/UX, color theory, typography, responsive layouts |
| `frontend-dev` | development | React, Vue, Angular, Svelte, TypeScript, modern JS |
| `backend-dev` | development | Node.js, Python, Go, databases, APIs, authentication |
| `fullstack-dev` | development | End-to-end web apps, deployment, DevOps |
| `debugging` | utilities | Find and fix bugs fast in any language |
| `code-review` | utilities | Security, performance, best practices, maintainability |
| `api-design` | development | REST, GraphQL, OpenAPI, versioning, auth |
| `sql-database` | development | Schemas, queries, optimization, migrations |

Use a skill's system prompt in OpenCode to get specialized behavior for that task.

## Model Detection

OpenCode UNLIMITED detects free models from the OpenCode gateway and ranks them by quality and context window:

```bash
opencode-proxy models list
opencode-proxy models best
```

---

## Credits

- **Development & Creator**: null
- `ebouther/opencode-unlimited-proxy` — free-tier gate research & multi-egress rotation strategy
- `jasonxu114514/opencode2api` — Go gateway engine + WARP userspace egress manager
- OpenCode — open-source terminal coding assistant

---

## License

[MIT](LICENSE)