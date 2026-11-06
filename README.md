# OpenCode UNLIMITED

> A local proxy for the OpenCode free tier. Cloudflare WARP rotates the exit
> IP on every request, so the quota never runs out.
> Termux, ARM64, no root, no Docker, no server of your own.

```bash
curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3
opencode-unlimited
```

That is the whole install. The rest of this page is what you get, how to fix
things when they break, and what else the proxy is good for.

---

## What you get

| | |
|---|---|
| Gateway | `opencode2api` v1.4.6 on `http://127.0.0.1:8080/v1` |
| Dashboard | `http://127.0.0.1:8081` |
| Egress | Cloudflare WARP IPv6, rotates on every 429/403 |
| CLI | OpenCode CLI 1.19.5, wired to the proxy for you |
| Commands | `opencode-unlimited` (menu) and `opencode-proxy` (scriptable) |

Requirements: an ARM64 Android device, Termux or a distro under `proot-distro`,
and about 300 MB of free space.

---

## Install

**One command** (works on Termux and inside proot-distro):

```bash
curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3
```

**From a clone** (needs `git`):

```bash
apt-get install -y git
git clone https://github.com/Inkflow-Gab/nullxOpenS.git
cd nullxOpenS
python3 setup.py install
```

**With the bootstrap script** (installs the missing packages first):

```bash
git clone https://github.com/Inkflow-Gab/nullxOpenS.git
cd nullxOpenS
bash install.sh
```

Inside proot-distro the installer uses `apt-get`, on Termux it uses `pkg`.
Both are detected automatically.

### Check it

```bash
opencode-proxy doctor
opencode-proxy status
```

Every line in the doctor output is either `ok` or `FAIL`. Start the gateway
if it is not running yet:

```bash
opencode-proxy start
```

---

## The two commands

`opencode-unlimited` runs the menu, or takes `start`, `start --continue`,
`stop`, `restart`, `status`.

`opencode-proxy` is the scriptable one:

| Command | What it does |
|---------|--------------|
| `start` / `stop` / `restart` | Control the gateway |
| `status` | Gateway, WARP state, exposed models |
| `test [model]` | One test request through the gateway |
| `bench [model]` | Time to the first token |
| `models list` / `models best` | The free models |
| `model <model-id>` | Change the default model |
| `thinking <mode>` | Reasoning effort: `low` `medium` `high` `max` `none` |
| `thinking status` | Show the current effort |
| `doctor` | Check the whole install |
| `repair` | Rewrite the commands and the config, put them back on PATH |
| `fix-dns` | Point `/etc/resolv.conf` at 1.1.1.1 and 8.8.8.8 |
| `rate-limit` | Scan the log for 429 and quota events |
| `logs` | Last lines of the gateway log |
| `autostart enable\|disable\|status` | Start on device boot |
| `config` | Print the OpenCode configuration |
| `backup` / `restore` | Save and restore the configs |
| `version` / `validate` | Versions and config check |
| `uninstall` | Remove everything the installer wrote |

---

## If something is wrong

Run this first, it repairs the commands, the config and the PATH:

```bash
opencode-proxy repair
```

Then work down the table:

| Symptom | Do this |
|---------|---------|
| `opencode-unlimited: command not found` | `export PATH="$HOME/.local/bin:$PATH"`, then `opencode-proxy repair`. The commands are also copied into `/usr/local/bin` (or `$PREFIX/bin` on Termux), so a new terminal usually fixes it. |
| `git: command not found` | `apt-get install -y git`. Only needed to clone or update, the proxy does not need it. |
| `bash: install.sh: No such file or directory` | You are not in the cloned folder. Run `ls`, then `cd nullxOpenS`. Or skip the clone and use the one command install. |
| `proxy is stopped` | `opencode-proxy start`, then `opencode-proxy status` |
| Gateway starts but never goes online | `opencode-proxy fix-dns` then `opencode-proxy restart`. Inside proot-distro the resolver is often `127.0.0.1`, which WARP cannot use. |
| Still `Free usage exceeded` | OpenCode is bypassing the proxy. `opencode-proxy doctor` must show `opencode.jsonc routes through the proxy` as `ok`. |
| The CLI does not start on Termux | `pkg install glibc-repo glibc-runner`, the CLI needs glibc. |
| The download failed during install | The installer keeps going and tells you the URL. Download it by hand and save it to `~/.opencode-proxy/bin/opencode2api`. |
| Want a clean slate | `opencode-proxy uninstall` then `python3 setup.py install` |

The log always tells you what the gateway was doing:

```bash
opencode-proxy logs
opencode-proxy rate-limit
```

---

## Beyond OpenCode

The gateway is a plain OpenAI compatible API. Anything that speaks
`/v1/chat/completions` can use it, not just the OpenCode CLI.

```bash
curl http://127.0.0.1:8080/v1/chat/completions \
  -H "Authorization: Bearer local-test-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"deepseek-v4.1-flash-free","messages":[{"role":"user","content":"hello"}]}'
```

Point a client at it:

| Client | What to enter |
|--------|---------------|
| Cline, Roo Code, Continue | Provider: OpenAI compatible, base URL `http://127.0.0.1:8080/v1`, key `local-test-key` |
| Aider | `OPENAI_API_BASE=http://127.0.0.1:8080/v1 OPENAI_API_KEY=local-test-key` |
| Cursor, Zed, Windsurf | Custom OpenAI provider, same base URL and key |
| Open WebUI, LibreChat, AnythingLLM, LobeChat | OpenAI connection, same base URL and key |
| Python SDK | `OpenAI(base_url="http://127.0.0.1:8080/v1", api_key="local-test-key")` |
| Node SDK | `new OpenAI({ baseURL: "http://127.0.0.1:8080/v1", apiKey: "local-test-key" })` |

What that buys you:

- **Run every request through WARP**, so the free tier of any client stops
  running out, not just OpenCode.
- **Use it as a backend for your own scripts**: summarise logs, translate
  release notes, triage errors, generate fixtures, feed a bot.
- **Compare models** with `opencode-proxy bench <model>` before picking one.
- **Watch the traffic** on the dashboard at `http://127.0.0.1:8081`.
- **Reach it from another device** by forwarding the port, for example
  `adb forward tcp:8080 tcp:8080`, then use `http://127.0.0.1:8080/v1` on the
  other machine. The gateway listens on localhost only, keep it that way
  unless you know what you are exposing.

---

## Models

| Model | Good for | Context |
|-------|----------|---------|
| `deepseek-v4.1-flash-free` | Code, algorithms, refactoring | 128K |
| `crouton-alpha-free` | Large documents, multimodal input | 1M |
| `nemotron-3.5-super-vl-free` | Vision and language tasks | 1M |
| `beam-free` | Step by step logic | 1M |
| `pulse-alpha-free` | Multimodal input | 1M |
| `big-pickle` | Planning, multi step reasoning | 200K |
| `nemotron-3.5-lightning-free` | Fast answers, commands | 262K |
| `glm-5.3-flash-free` | General knowledge | 128K |
| `flint-40b-free` | Open weight models | 128K |
| `mimo-v2.6-flash-free` | Small, quick assistant | 128K |

The gateway refreshes this list on its own, `opencode-proxy models list`
shows what is live right now.

---

## Files

| Path | What it holds |
|------|---------------|
| `~/.opencode-proxy/config.json` | Gateway configuration |
| `~/.opencode-proxy/proxy.log` | Gateway log |
| `~/.opencode-proxy/proxy.pid` | PID of the running gateway |
| `~/.opencode-proxy/backups/` | Backups from `opencode-proxy backup` |
| `~/.config/opencode/opencode.jsonc` | OpenCode configuration |
| `~/.local/bin/opencode-proxy` | The gateway command |
| `~/.local/bin/opencode-unlimited` | The launcher |
| `~/.local/bin/opencode` | The OpenCode CLI wrapper |

## Uninstall

```bash
opencode-proxy uninstall
```

It stops the gateway and removes the files above, including the generated
`opencode.jsonc`. Take a backup first with `opencode-proxy backup` if you
want to keep it.

## Credits

- `jasonxu114514/opencode2api` - the gateway engine and the WARP egress manager
- `ebouther/opencode-unlimited-proxy` - the free tier and multi egress research
- OpenCode - the terminal coding assistant this project wraps

## License

[MIT](LICENSE)
