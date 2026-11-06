# NullxOpenS × REA — Architecture & Compatibility Report

**Phase One deliverable — repository audit findings.**  
Destination: `Inkflow-Gab/nullxOpenS` | Upstream: `morluto/rea` (`rea-agents` npm package v6.8.0)

---

## 1. Executive summary

NullxOpenS already integrates REA, but the integration is minimal and fragile:

- REA is installed **unpinned** (`npm install --global rea-agents`) with no version control.
- No Node.js engine verification against REA's requirement (`^22.23.4 || ^24.22.1 || >=26.12.1`). Node 24.22.0 (the user's previously installed version) is **insufficient** — REA needs >=24.22.1.
- On Linux (incl. proot-distro Ubuntu) no `--prefix` is used, so the global npm prefix may require root or collide with system installs.
- No uninstall, no diagnostics, no MCP management, no Android ARM64-specific handling beyond an arch gate.
- The `opencode-proxy rea {setup|analyze|update|help|status|connect}` surface is backward compatible and must be preserved.

This report documents the current state, the chosen integration approach, and the implementation plan carried out in Phases Two–Nine.

---

## 2. NullxOpenS audit (destination repo)

### 2.1 Files inspected

| File | Role |
|------|------|
| `setup.py` (97 KB) | Single-file Python management layer: install, daemon (opencode2api proxy), CLI wrapper, menu shell, skills, models, REA |
| `install.sh` | Thin Termux/bash bootstrap: arch gate (aarch64/arm64 only), dep install, copies `setup.py` to `~/.opencode-proxy`, delegates to `setup.py install` |
| `README.md` | User-facing docs incl. REA section |
| `config.example.json` | opencode2api gateway config |
| `opencode.example.jsonc` | OpenCode agent config example |
| `LICENSE` | MIT |
| `.gitignore` | `__pycache__/`, `*.pyc` |

### 2.2 Existing REA integration (in `setup.py`)

Constants:
- `REA_PKG = "rea-agents"`, `REA_SETUP_URL = "https://github.com/morluto/rea"` — **no version pin**

`install_rea()`:
- Runs `npm install --global rea-agents` (unpinned, no `--prefix`)
- Skips if `rea` already on PATH
- No Node.js version check, no diagnostics

`do_rea(subcmd, arg)` — subcommands:
- `status` — `rea --version`, prints `which rea`
- `setup` — `rea setup` (interactive)
- `analyze` — `rea analyze-javascript-application <path> --json`
- `update` — `rea update`
- `help` — `rea --help`
- `connect` — `do_rea_connect()`: creates `~/.local/bin/rea-unlimited` wrapper exporting `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `REA_MODEL` pointing at the local opencode2api proxy

`do_rea_connect()` requires the proxy to be healthy (`health_ok()`), installs `rea-agents` globally if missing, writes an executable wrapper.

Wiring:
- `do_install()` calls `install_rea()`
- `MANAGER_SH` (`opencode-proxy`) delegates `rea) python3 "$SETUP" rea "${2:-}" "${3:-}"`
- `UNLIMITED_SH` (`opencode-unlimited`) menu: REA is main-menu option 1 with a sub-menu (Status, Setup, Connect, Analyze, Update, Help, Back)

### 2.3 Gaps identified

1. No version pin → non-reproducible installs, silent breakage on upstream releases
2. No Node.js engine verification → REA fails at runtime on Node <22.23.4 / <24.22.1 / <26.12.1
3. No `--prefix` on Linux → potential root/permission conflicts in proot-distro Ubuntu
4. No `uninstall` for REA → `do_uninstall()` does not remove `rea`
5. No diagnostics/doctor for REA dependency state
6. No MCP server management (`rea mcp`) exposed from NullxOpenS
7. No Android ARM64-specific dependency validation beyond the arch gate

---

## 3. REA upstream audit (`morluto/rea`, v6.8.0)

### 3.1 package.json highlights

| Field | Value |
|-------|-------|
| name | `rea-agents` |
| version | `6.8.0` |
| bin | `rea` → `scripts/rea.mjs`; `rea-agents` → `scripts/rea.mjs` |
| engines.node | `^22.23.4 || ^24.22.1 || >=26.12.1` |
| packageManager | `npm@11.16.0` |
| type | `module` |
| mcpName | `io.github.morluto/rea` |
| optionalDependencies | `frida@17.23.2` |
| files | `dist`, `install.sh`, `scripts/rea.mjs`, `scripts/rea-android-workspace-guardian.mjs`, `bridge/*`, `skills`, LICENSE, etc. |

### 3.2 Entry points

- **CLI**: `scripts/rea.mjs` — dispatches:
  - `rea mcp` / `rea --mcp` → MCP server over stdio (`dist/mcp/main.js`)
  - `rea mpc add` / `rea mcp doctor` → MCP registration & validation
  - everything else → Incur CLI (`dist/cli-runtime/cli.js`)
- **MCP server**: `src/main.ts` → `runEntrypoint()` → `serveStdio` from `@modelcontextprotocol/server`; also supports streamable HTTP (`rea mcp --http`)
- **Installer**: `install.sh` — strict Node engine check, `npm install --global --prefix $HOME/.local rea-agents@<ver>` on Linux, default global prefix on macOS, then `rea setup` when a TTY is available

### 3.3 CLI commands relevant to NullxOpenS (verified)

`setup`, `uninstall`, `update`, `doctor`, `mcp` (add/doctor), `analyze`, `analyze-javascript-application`, `inspect-apk-signature`, `inspect-android-package`, `capabilities`, plus 200+ analysis/provider tools exposed via MCP.

### 3.4 `rea doctor` output (verified)

Structured health report. Checks `node` (version vs engines), `host`, and analysis engines (`hopper`, `ghidra`, `ida-registration`, `jadx`, …). Each check: `ok`, `classification` (healthy / missing_dependency / missing_analysis_engine), `detail`, `remediation`. Exit code 0 even when unhealthy (reports status in payload).

### 3.5 `rea mcp doctor` output (verified)

```json
{"healthy":true,"adapter":"production-stdio","server":{"name":"rea","version":"6.8.0","protocol_version":"2025-11-25"},
 "inventory":{"tools":{"expected":229,"observed":229,...},"prompts":{"expected":6,"observed":6,...}},
 "request_flow":{"tool":"binary_session","ok":true}, ...}
```
MCP server starts over stdio, registers 229 tools + 6 prompts, validates identity and a sample request.

### 3.6 `rea analyze-javascript-application` (verified)

Statically reconstructs a local JS/Electron app directory. Emits JSONL progress then a final Evidence JSON (modules, imports, exports, semantic graph, limitations). Works without a native analysis engine — **the primary Android-compatible analysis provider**.

### 3.7 Platform compatibility assessment

| Dependency / area | Android ARM64 (Termux + proot) | Notes |
|-------------------|-------------------------------|-------|
| Node.js + npm | Supported if a REA-compatible release is available | Termux `pkg nodejs` may lag REA's engine floor; verify `node -p process.versions.node` |
| `rea-agents` npm package | Pure JS + some optional native deps | `frida` optional; `playwright-core` (browser) needs Chrome — heavy, often impractical on Android |
| Native analysis engines (Hopper/Ghidra/IDA/Kuna) | **Unsupported on-device** | Desktop-only; require x86_64 macOS/Windows/Linux and licenses |
| JADX (APK decompilation) | **Requires caller-supplied headless JADX MCP JAR** | REA does not download/install it |
| Apktool | **Caller-supplied** | Not bundled |
| adb (Android devices) | **Caller-supplied** | Works if `adb` is on PATH |
| Static JS / .NET / APK signature / ELF notes / etc. | **Supported** (pure static inspection) | No native engine needed |
| `rea mcp` over stdio | **Supported** | Node.js stdio works in Termux/proot |

**Verdict**: The `rea-agents` package installs and runs on Android ARM64 provided a compliant Node.js is present. Static JavaScript/APK-signature/ELF inspection works on-device. Deep native binary analysis (Hopper/Ghidra/IDA) and browser/Playwright capture are **not** practical on-device and are classified as requiring an external analysis machine or additional dependencies.

---

## 4. Chosen integration approach (Phase Two)

**Approach: Managed npm package installation with version pinning** (of the four considered).

Rationale:
- Maintainable: upstream publishes `rea-agents` to npm; `rea update` keeps it current.
- Mobile-compatible: works in Termux and proot-distro Ubuntu with a local npm prefix (`$HOME/.local`), no root.
- Upstream update support: `npm install --global --prefix $HOME/.local rea-agents@<ver>` + `rea update`.
- No duplication: we never copy REA source; the Python layer only manages the npm package lifecycle.
- Reproducible: version pinned (`6.8.0` by default, overridable).
- Reliable executable path: `$HOME/.local/bin/rea`, already on PATH via NullxOpenS's `ensure_path()`.

The pinned version tracks `package.json#engines.node`. Node 24.22.0 is rejected (needs >=24.22.1).

---

## 5. Integration design (Phases Three–Five)

### 5.1 Python management layer (setup.py)

New/changed constants:
- `REA_VER = "6.8.0"` — pinned release
- `REA_PKG = "rea-agents"`, `REA_PKG_VER = "rea-agents@6.8.0"`
- `REA_NODE_ENGINES = "^22.23.4 || ^24.22.1 || >=26.12.1"`
- `REA_BIN = LOCAL_BIN / "rea"` (`$HOME/.local/bin/rea`)

New functions:
- `node_version()` / `check_node_engines()` — parse `node --version`, validate against engines; report remediation (nvm/fnm/direct download)
- `install_rea(dry_run)` — `npm install --global --prefix $HOME/.local rea-agents@6.8.0` (Linux/Termux); version-pinned; skips if already installed at the right version
- `update_rea(dry_run)` — `rea update`
- `uninstall_rea(dry_run)` — `npm uninstall --global --prefix $HOME/.local rea-agents`
- `rea_status()` — version, binary path, Node compatibility
- `rea_diagnostics()` — runs `rea doctor` and reports Node/npm/rea/engine state
- `rea_mcp_config()` — prints agent-ready MCP registration JSON (`command: rea`, `args: ["mcp"]`)
- `rea_mcp_doctor()` — runs `rea mcp doctor`
- `rea_mcp_start()` — launches `rea mcp` (for manual/stdout testing; not used inside stdio MCP)

`do_rea(subcmd, arg)` extended subcommands (backward compatible):
- `status`, `setup`, `analyze`, `update`, `help`, `connect` — preserved
- `install` — managed install
- `uninstall` — managed removal
- `diagnostics` / `doctor` — dependency & readiness report
- `node` — Node.js engine check
- `mcp config` / `mcp doctor` / `mcp start` — MCP management

All subprocess calls use `capture=True`, exit-code handling, timeouts, and readable errors.

### 5.2 CLI (Phase Three)

- `opencode-proxy rea {setup|install|update|uninstall|status|diagnostics|help|analyze|connect|node|mcp ...}`
- Interactive REA sub-menu extended with Diagnostics, MCP config, Uninstall
- `opencode-unlimited` menu retains REA as option 1
- Backward-compatible: all previously documented `rea` subcommands behave identically

### 5.3 MCP (Phase Four)

- Use REA's **native** MCP server (`rea mcp` over stdio) — no Python proxy, no duplicate tool implementation
- `opencode-proxy rea mcp config` emits the JSON to paste into Claude Code / Cursor / Codex settings
- `opencode-proxy rea mcp doctor` validates startup + tool registration (229 tools, 6 prompts)
- `opencode-proxy rea mcp start` runs the server foreground for testing
- No terminal UI output inside stdio MCP communication (REA's MCP server owns stdio; NullxOpenS never interleaves)

### 5.4 Android ARM64 (Phase Five)

- Existing arch gate (`check_arch()`: aarch64/arm64 only) retained
- Node.js engine verification added (Termux `pkg nodejs` may be below REA's floor → actionable remediation)
- npm `--prefix $HOME/.local` avoids root and system-prefix conflicts in proot-distro Ubuntu
- Classification of providers: static JS/APK-signature/ELF = supported on-device; Hopper/Ghidra/IDA/JADX/Playwright = external or additional dependencies
- No root required; no x86_64 binaries; executable permissions preserved

---

## 6. Testing performed (Phase Eight)

All tests executed on the development host (**x86_64 Linux, Node 22.22.3, npm 10.9.8, Python 3.11.2**).  
⚠️ **This host is NOT ARM64/Termux**, so Android ARM64 behavior is inferred from REA's documented platform support and the `prepareCliProcessEnvironment` android branch; it is classified as "theoretically compatible, not executed on target."

| Test | Result |
|------|--------|
| `npm install --global --prefix ... rea-agents@6.8.0` | ✅ Installed (engine warning on Node 22.22.3; installs anyway) |
| `rea --version` | ✅ `6.8.0` |
| `rea --help` | ✅ Lists all commands |
| `rea doctor` | ✅ Structured health output; correctly flags Node 22.22.3 as below engine floor |
| `rea mcp doctor --format json` | ✅ `healthy: true`, 229 tools, 6 prompts, stdio adapter |
| `rea analyze-javascript-application <dir> --json` | ✅ Produces Evidence JSON (modules, exports, semantic graph, limitations) |
| `rea mcp add --help` | ✅ `--agent`, `--command`, `--no-global` options |

ARM64/Termux/prooot: **not executed** in this sandbox (x86_64 host). Documented as requiring verification on target.

---

## 7. Files modified (Phase Two–Four)

All changes are in `/home/user/nullxOpenS/setup.py`:

1. REA constants: version pin, package spec, engines, binary path
2. Node.js engine detection & verification helpers
3. `install_rea()` — version-pinned, `--prefix` on Linux/Termux
4. New: `update_rea()`, `uninstall_rea()`, `rea_status()`, `rea_node_check()`, `rea_diagnostics()`, `rea_mcp_config()`, `rea_mcp_doctor()`
5. `do_rea()` — extended subcommand set (backward compatible)
6. `do_rea_connect()` — retained, REA install ensured via managed path
7. `do_uninstall()` — now removes REA binary
8. `do_doctor()` — includes Node/REA readiness
9. `MANAGER_SH` / `UNLIMITED_SH` — REA sub-menu extended (Diagnostics, MCP config, Uninstall)
10. `do_install()` — calls version-pinned `install_rea()`

Documentation files updated: `README.md` (REA section), this report (`REA_INTEGRATION_ARCHITECTURE.md`).

---

## 8. Unsupported features & reasons

| Feature | Classification | Reason |
|---------|---------------|--------|
| Hopper / Ghidra / IDA / Kuna native analysis | Unsupported on-device | Desktop-only, licensed, x86_64 macOS/Windows/Linux |
| JADX headless APK decompilation | Unsupported on-device (without caller-supplied JAR) | REA does not download/install JADX; requires `REA_JADX_MCP_JAR` |
| Playwright / browser capture | Unsupported on-device | Requires Chrome-family browser; heavy for Android |
| Apktool resource decoding | Unsupported on-device (without caller-supplied binary) | Caller-supplied launcher |
| Node.js <22.23.4 / <24.22.1 / <26.12.1 | Unsupported | Below `engines.node`; `rea doctor` reports `missing_dependency` |
| Non-ARM64 (x86_64) | Unsupported by NullxOpenS | `check_arch()` gates to aarch64/arm64 |

---

## 9. Installation instructions (NullxOpenS + REA)

```bash
# 1. Install NullxOpenS (includes managed REA)
curl -fsSL https://raw.githubusercontent.com/Inkflow-Gab/nullxOpenS/main/setup.py | python3

# 2. Verify REA
opencode-proxy rea status
opencode-proxy rea diagnostics

# 3. Analyze a JavaScript/Electron app (works on-device, static)
opencode-proxy rea analyze /path/to/app

# 4. Connect REA to the OpenCode proxy (WARP rotation)
opencode-proxy start
opencode-proxy rea connect

# 5. MCP — register REA with your AI agent
opencode-proxy rea mcp config   # copy the JSON into your agent's MCP settings
opencode-proxy rea mcp doctor   # validate startup + tools

# 6. Update REA
opencode-proxy rea update
```

---

## 10. Remaining work

- Execute the full test suite on a real Android 15 ARM64 device (Termux + Ubuntu proot-distro) to confirm Node.js availability, `rea-agents` install, `analyze-javascript-application`, and `rea mcp` stdio behavior under Termux.
- If Termux `pkg nodejs` trails REA's engine floor, document installing Node via nvm/fnm or a Node.js binary tarball for `aarch64`.
- Consider a dedicated `rea_manager.py` module if `setup.py` growth harms maintainability (currently kept as one file for incremental, low-risk change).
- Add CI that runs `setup.py dry-run` and `rea doctor` on ARM64 runners where available.
