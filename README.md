# OpenCode UNLIMITED

OpenCode UNLIMITED installs and controls the [opencode2api](https://github.com/jasonxu114514/opencode2api)
gateway and the OpenCode CLI on Android (Termux). The gateway rotates through
Cloudflare WARP IPv6 exits, so the free tier of OpenCode does not run out of
requests because every request leaves the device from a different address.

No root, no Docker, no server of your own.

## Requirements

- An ARM64 Android device (`aarch64`)
- Termux, or a Linux distro running under `proot-distro`
- Around 300 MB of free space for the gateway, the CLI and their dependencies

## Installation

### One command

```bash
curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3
```

### From a clone

```bash
git clone https://github.com/Inkflow-Gab/nullxOpenS.git
cd nullxOpenS
python3 setup.py install
```

### With the bootstrap script

`install.sh` installs the missing packages first and then hands over to
`setup.py`:

```bash
git clone https://github.com/Inkflow-Gab/nullxOpenS.git
cd nullxOpenS
bash install.sh
```

### Inside proot-distro

The installer detects `apt-get` and switches to it, so the same command works
inside Ubuntu under `proot-distro`:

```bash
proot-distro login ubuntu
apt update && apt install -y python3 curl
curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3
```

### What the installer does

1. Installs the missing packages (`curl`, `jq`, `proot`, `python`, and on
   Termux `glibc-runner` plus `termux-tools`)
2. Downloads the `opencode2api` gateway into `~/.opencode-proxy/bin`
3. Downloads the OpenCode CLI into `~/.local/bin/opencode-bin`
4. Writes the gateway config to `~/.opencode-proxy/config.json`
5. Writes `~/.config/opencode/opencode.jsonc` so OpenCode talks to the local
   gateway instead of the free tier directly
6. Writes the `opencode-proxy` and `opencode-unlimited` commands into
   `~/.local/bin` and adds that folder to `PATH` in `~/.bashrc`

## Checking the install

```bash
opencode-proxy doctor
```

Every line is either `ok` or `FAIL`. If the gateway is not online yet, start it:

```bash
opencode-proxy start
opencode-proxy status
```

The API is then reachable at `http://127.0.0.1:8080/v1` and the dashboard at
`http://127.0.0.1:8081`.

## Usage

### The launcher

```bash
opencode-unlimited
```

Without arguments it opens a menu: start the proxy and the CLI together,
resume the last session, switch models, change the thinking mode, adjust the
terminal font, fix DNS, toggle auto start, run the doctor, or read the rate
limit log.

The same thing works with arguments:

```bash
opencode-unlimited start
opencode-unlimited start --continue
opencode-unlimited stop
opencode-unlimited restart
opencode-unlimited status
```

### The proxy command

| Command | Description |
|---------|-------------|
| `opencode-proxy start` | Start the gateway in the background |
| `opencode-proxy stop` | Stop the gateway |
| `opencode-proxy restart` | Stop and start the gateway again |
| `opencode-proxy status` | Show the gateway, the WARP state and the model count |
| `opencode-proxy test [model]` | Send a test request through the gateway |
| `opencode-proxy bench [model]` | Measure the time to the first token |
| `opencode-proxy logs` | Print the last lines of the gateway log |
| `opencode-proxy models list` | List the free models with their context size |
| `opencode-proxy models best` | Show the three best models |
| `opencode-proxy model <model-id>` | Change the default model |
| `opencode-proxy thinking <mode>` | Set the reasoning effort |
| `opencode-proxy thinking status` | Show the current reasoning effort |
| `opencode-proxy config` | Print the current OpenCode configuration |
| `opencode-proxy doctor` | Check the whole install |
| `opencode-proxy fix-dns` | Point `/etc/resolv.conf` at 1.1.1.1 and 8.8.8.8 |
| `opencode-proxy rate-limit` | Scan the log for 429 and quota events |
| `opencode-proxy autostart enable` | Start the proxy when the device boots |
| `opencode-proxy autostart disable` | Stop starting it on boot |
| `opencode-proxy autostart status` | Show the auto start state |
| `opencode-proxy backup` | Save the configs into a tarball |
| `opencode-proxy restore [file]` | Restore a backup |
| `opencode-proxy update` | Download the latest `setup.py` |
| `opencode-proxy uninstall` | Remove everything the installer wrote |
| `opencode-proxy version` | Show the installed versions |

### Thinking mode

DeepSeek and the other reasoning models accept a reasoning effort. It is stored
in `~/.config/opencode/opencode.jsonc` and picked up the next time OpenCode
starts:

```bash
opencode-proxy thinking low
opencode-proxy thinking medium
opencode-proxy thinking max
opencode-proxy thinking none
opencode-proxy thinking status
```

### Auto start on boot

Needs the Termux boot app:

```bash
opencode-proxy autostart enable
opencode-proxy autostart status
```

The script is written to `~/.termux/boot/opencode-proxy-start.sh`.

## Free models

The gateway exposes the free tier of OpenCode through the proxy. The ones the
installer knows about:

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

The gateway refreshes the list itself, so `opencode-proxy models list` can
show more than what is written here.

## Troubleshooting

**"Free usage exceeded" or other rate limits**

OpenCode is most likely talking to the upstream directly instead of through
the gateway:

```bash
opencode-proxy status      # the gateway has to be online
opencode-proxy doctor      # "opencode.jsonc routes through the proxy" has to be ok
opencode-proxy config      # baseURL should be http://127.0.0.1:8080/v1
opencode-proxy test deepseek-v4.1-flash-free
```

Always start OpenCode through `opencode-unlimited` or `opencode-proxy` so the
requests leave through WARP.

**The gateway starts but never comes online**

WARP needs a working resolver. Inside proot-distro `/etc/resolv.conf` often
points at `127.0.0.1`, which the userspace WARP client cannot use:

```bash
opencode-proxy fix-dns
opencode-proxy restart
```

**The OpenCode CLI does not start on Termux**

The CLI is a glibc binary and needs the runner:

```bash
pkg install glibc-repo glibc-runner
```

After that `opencode-proxy doctor` should show `package grun` as installed.

**Check the log**

```bash
opencode-proxy logs
opencode-proxy rate-limit
```

## Files

| Path | What it holds |
|------|---------------|
| `~/.opencode-proxy/config.json` | Gateway configuration |
| `~/.opencode-proxy/proxy.log` | Gateway log |
| `~/.opencode-proxy/proxy.pid` | PID of the running gateway |
| `~/.opencode-proxy/backups/` | Backups made by `opencode-proxy backup` |
| `~/.config/opencode/opencode.jsonc` | OpenCode configuration |
| `~/.local/bin/opencode-proxy` | The gateway command |
| `~/.local/bin/opencode-unlimited` | The launcher |
| `~/.local/bin/opencode` | The OpenCode CLI wrapper |

## Uninstall

```bash
opencode-proxy uninstall
```

It stops the gateway and removes the files listed above, including the
generated `opencode.jsonc`. Make a backup first with
`opencode-proxy backup` if you want to keep it.

## Credits

- `jasonxu114514/opencode2api` - the gateway engine and the WARP egress manager
- `ebouther/opencode-unlimited-proxy` - the free tier and multi egress research
- OpenCode - the terminal coding assistant this project wraps

## License

[MIT](LICENSE)
