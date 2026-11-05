# OpenCode UNLIMITED 🚀

OpenCode Unlimited on Android (Termux) — rotating Cloudflare WARP egress pool for unlimited free OpenCode models. No root, no Docker, no external servers.

<p align="center">
  <img src="https://img.shields.io/badge/platform-Android%20%7C%20Termux%20ARM64-green?style=for-the-badge" alt="platform">
  <img src="https://img.shields.io/badge/engine-opencode2api%20v1.4.6-blue?style=for-the-badge" alt="engine">
  <img src="https://img.shields.io/badge/opencode-v1.19.5-purple?style=for-the-badge" alt="opencode">
  <img src="https://img.shields.io/badge/license-MIT-red?style=for-the-badge" alt="license">
</p>

---

## About 📖

OpenCode UNLIMITED is an all-in-one Python setup that installs and manages the `opencode2api` gateway plus the OpenCode CLI. It rotates through Cloudflare WARP IPv6 exits to eliminate per-IP rate limits on the anonymous free tier — giving you unlimited access to OpenCode's free models.

Works on native Termux **and** inside `proot-distro login ubuntu` — it auto-detects `pkg` vs `apt` and skips Termux-only packages when not on Termux.

Built and maintained by **null** 🛠️

---

## Features ✨

- One-command setup via `setup.py` (Termux + Ubuntu/proot-distro)
- `opencode2api` v1.4.6 gateway with WARP IPv6 egress rotation 🌐
- OpenCode CLI v1.19.5 via `glibc-runner` (`grun`)
- Double-fork daemon spawner — survives terminal close
- OpenAI-compatible `/v1` endpoint at `http://127.0.0.1:8080/v1`
- Web dashboard at `http://127.0.0.1:8081`
- 10 verified free-tier models exposed
- **Skill system** — 400+ skills from alirezarezvani/claude-skills (search, categories, apply-skill, sync, add/remove)
- **Model management** — switch, bench, and detect free models
- **Diagnostics** — `doctor` command checks your whole setup
- No Docker, no root, no external server required

---

## Quick Start 🚀

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
opencode-unlimited start           # starts proxy + launches CLI together
opencode-unlimited start --continue # starts proxy + resumes previous session
opencode-unlimited status          # check both proxy and CLI
opencode-unlimited stop            # stop everything
```

Or use them separately:

```bash
opencode-proxy start
opencode-proxy status
opencode
```

---

## Commands 📋

| Command | Description |
|---------|-------------|
| `python3 setup.py install` | Full one-command setup |
| `opencode-proxy start` | Start the proxy daemon |
| `opencode-proxy stop` | Stop the proxy daemon |
| `opencode-proxy restart` | Restart the proxy daemon |
| `opencode-proxy status` | Check daemon + WARP + model status |
| `opencode-proxy test [model]` | Send a test chat request |
| `opencode-proxy bench [model]` | Benchmark a model (time to first token) |
| `opencode-proxy logs` | Stream recent proxy logs |
| `opencode-proxy config` | Show current OpenCode configuration |
| `opencode-proxy doctor` | Run system diagnostics |
| `opencode-proxy sync` | Re-sync skills from claude-skills repo |
| `opencode-proxy continue` | Resume previous OpenCode session (`opencode --continue`) |
| `opencode-proxy fix-dns` | Fix `/etc/resolv.conf` for WARP DNS (1.1.1.1, 8.8.8.8) |
| `opencode-proxy zoom-in` | Increase terminal font size (Termux) |
| `opencode-proxy zoom-out` | Decrease terminal font size (Termux) |
| `opencode-proxy zoom-reset` | Reset terminal font size to default |
| `opencode-proxy thinking <mode>` | Set model thinking mode (low, medium, max) |
| `opencode` | Launch OpenCode CLI TUI |
| `opencode-unlimited start` | Start proxy + launch CLI together |
| `opencode-unlimited start --continue` | Start proxy + resume previous OpenCode session |
| `opencode-unlimited stop` | Stop proxy + CLI |
| `opencode-unlimited restart` | Restart proxy + CLI |
| `opencode-unlimited status` | Check both proxy and CLI |

### Skills (from alirezarezvani/claude-skills) 🎯

| Command | Description |
|---------|-------------|
| `opencode-proxy skills install` | Download skills from claude-skills repo |
| `opencode-proxy skills sync` | Re-sync skills from claude-skills repo |
| `opencode-proxy skills list` | List all installed skills |
| `opencode-proxy skills categories` | List skill categories |
| `opencode-proxy skills search <term>` | Search skills by name/category/description |
| `opencode-proxy skills show <name>` | Show skill details & system prompt |
| `opencode-proxy skills add <name>` | Create a custom skill |
| `opencode-proxy skills remove <name>` | Remove a skill |
| `opencode-proxy apply-skill <name>` | Apply a skill's system prompt to OpenCode config |

### Models ⚡

| Command | Description |
|---------|-------------|
| `opencode-proxy models list` | List all detected free models with rankings |
| `opencode-proxy models best` | Show top 3 free models |
| `opencode-proxy model <name>` | Switch default OpenCode model |

---

## Architecture 🏗️

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

## Models Exposed ⚡

| Model | Use Case | Context |
|-------|----------|---------|
| `deepseek-v4.1-flash-free` | Code, algorithms, refactoring ⭐ | 128K |
| `big-pickle` | Multi-step reasoning, planning | 200K |
| `crouton-alpha-free` | Massive context, multimodal docs ⭐ | 1M |
| `nemotron-3.5-super-vl-free` | Vision-language tasks ⭐ | 1M |
| `nemotron-3.5-lightning-free` | Low-latency scripts, commands | 262K |
| `glm-5.3-flash-free` | General knowledge | 128K |
| `beam-free` | Step-by-step logic | 1M |
| `mimo-v2.6-flash-free` | Compact quick assistant | 128K |
| `flint-40b-free` | Open-weight foundation | 128K |
| `pulse-alpha-free` | Multimodal input | 1M |

⭐ = Top 3 recommended free models

---

## Skills 🎯

OpenCode UNLIMITED downloads skills from **alirezarezvani/claude-skills** — 400+ production-ready skills across 20+ domains (engineering, marketing, c-level advisory, business, compliance, finance, productivity, research, and more). Each skill includes a system prompt that tells OpenCode how to behave for a specific task.

### Install skills

```bash
opencode-proxy skills install
```

This shows a live progress bar while downloading skills from GitHub.

### List installed skills

```bash
opencode-proxy skills list
```

### Browse skill categories

```bash
opencode-proxy skills categories
```

### Search for a skill

```bash
opencode-proxy skills search frontend
```

### Show a skill's content

```bash
opencode-proxy skills show agent-memory
```

### Create a custom skill

```bash
opencode-proxy skills add my-web-skill
# Then enter: description, category, and system prompt
```

### Remove a skill

```bash
opencode-proxy skills remove my-web-skill
```

---

## Applying Skills to OpenCode 🔧

Skills are **system prompts** — they change how OpenCode behaves. Apply a skill directly to your OpenCode configuration:

### Step 1: Apply a skill

```bash
opencode-proxy apply-skill frontend-dev
```

This writes the skill's system prompt into your OpenCode config (`~/.config/opencode/opencode.jsonc`).

### Step 2: Restart OpenCode

```bash
opencode-unlimited restart
```

### Step 3: Use OpenCode normally

OpenCode will now behave according to the skill's system prompt. Switch models if needed:

```bash
opencode-proxy model crouton-alpha-free
```

Or browse and preview skills before applying:

```bash
opencode-proxy skills show agent-memory
```

---

## Model Detection & Switching 🔄

OpenCode UNLIMITED detects free models from the OpenCode gateway and ranks them by quality and context window:

```bash
opencode-proxy models list
opencode-proxy models best
```

Switch your default model:

```bash
opencode-proxy model deepseek-v4.1-flash-free
```

Then restart OpenCode:

```bash
opencode-unlimited restart
```

---

## Diagnostics 🩺

Check that your whole setup is healthy:

```bash
opencode-proxy doctor
```

This verifies Python, architecture, packages, binaries, configs, skills, gateway connectivity, and that OpenCode is routed through the proxy — and gives you actionable fix suggestions.

If the proxy can't connect (DNS/WARP blocked), run:

```bash
opencode-proxy fix-dns
```

---

## Resume a Session (--continue) 🔄

OpenCode UNLIMITED supports resuming your previous OpenCode conversation with the `--continue` flag:

```bash
opencode --continue
```

This forwards `--continue` straight to the OpenCode CLI (`opencode-bin`), so it picks up right where your last session left off.

You can also trigger it through the proxy manager:

```bash
opencode-proxy continue
```

Both are equivalent — `opencode --continue` is the direct form, `opencode-proxy continue` goes through the manager wrapper.

## Troubleshooting 🩺

### Still seeing "Free usage exceeded" / rate-limit errors?

This means OpenCode is hitting OpenCode's servers directly instead of going through the proxy. Fix it:

**Step 1: Make sure the proxy is running**
```bash
opencode-proxy start
opencode-proxy status   # should show gateway online + WARP active
```

**Step 2: Fix DNS if WARP can't connect**
```bash
opencode-proxy fix-dns
opencode-proxy restart
```

**Step 3: Confirm OpenCode is routed through the proxy**
```bash
opencode-proxy doctor   # check "opencode.jsonc → proxy" shows "routed"
opencode-proxy config   # baseURL should be http://127.0.0.1:8080/v1
```

**Step 4: Test through the proxy**
```bash
opencode-proxy test deepseek-v4.1-flash-free
```

If all checks pass, launch OpenCode through the proxy:
```bash
opencode-unlimited start
opencode --continue
```

Never run `opencode` directly — always go through `opencode-proxy` / `opencode-unlimited` so WARP rotates your egress IP.

## Terminal Zoom 🔍

If you can't pinch-to-zoom in your Android terminal, use these commands to adjust the Termux font size:

```bash
opencode-proxy zoom-in    # make text bigger
opencode-proxy zoom-out   # make text smaller
opencode-proxy zoom-reset # back to default
```

These modify `~/.termux/termux.properties` and reload Termux settings automatically.

## Model Thinking 🧠

Set the reasoning/thinking mode for your models (DeepThink max for DeepSeek):

```bash
opencode-proxy thinking low     # minimal reasoning
opencode-proxy thinking medium  # balanced reasoning
opencode-proxy thinking max     # DeepThink max — DeepSeek's deepest reasoning
opencode-proxy thinking none    # disable thinking
opencode-proxy thinking status  # show visual thinking indicator
```

Then restart OpenCode to apply:

```bash
opencode-unlimited restart
```

Valid modes: `low`, `medium`, `max`, `high`, `none`

## Visual Thinking Indicator 🔍

Run `opencode-proxy thinking status` or `opencode-proxy doctor` to see a visual indicator:

- `● thinking: MAX` (magenta) — DeepThink max, DeepSeek's deepest reasoning
- `▲ thinking: high` (red) — high reasoning effort
- `▲ thinking: medium` (yellow) — balanced reasoning
- `▲ thinking: low` (blue) — minimal reasoning
- `○ thinking: off` (dim) — thinking disabled

This writes the thinking config into `~/.config/opencode/opencode.jsonc` so the model uses the specified reasoning effort on every request.

## Credits 🏅

- **Development & Creator**: null
- `ebouther/opencode-unlimited-proxy` — free-tier gate research & multi-egress rotation strategy
- `jasonxu114514/opencode2api` — Go gateway engine + WARP userspace egress manager
- OpenCode — open-source terminal coding assistant
- `alirezarezvani/claude-skills` — 400+ production-ready skill prompts

---

## License

[MIT](LICENSE)