Agentd MCP Server
=================

Overview
- Exposes your tmux-based async job runner (agentd) over the Model Context Protocol (MCP).
- Targeting modes: explicit pane / key / auto / self（起動環境がtmux内の場合の既定候補）。
- Tools: `tmux.run`, `tmux.status`, `tmux.logs`, `tmux.stop`。
- Resources: `job://{token}`（JSON）, `log://{token}`（text）。

Prerequisites
- tmux 3.x and the local scripts in `bin/` (`agentd-bootstrap`, `job-run`, `job-logs`, `job-stop`, `agentd-send`, `agentd-filter`).
- Python 3.10+.

Setup
1) Create venv and install dependencies (already done if you followed the CLI steps):

   ```bash
   python3 -m venv .venv-mcp
   . .venv-mcp/bin/activate
   pip install "mcp[cli]" watchfiles
   ```

2) Start your original CLI in tmux and record pane (once):

   ```bash
   export PATH="$PWD/bin:$PATH"
   agentd-bootstrap  # saves ~/.agentd/agent_pane
   ```

3) Run the MCP server:

   ```bash
   bin/mcp-agentd
   ```

Zero-config behavior
- `bin/mcp-agentd` を起動するだけで利用可能。既定のターゲット解決は `auto`（直近アクティブなtmuxクライアントのセッション→`cli.0`）。
- 必要なら `tmux.bootstrap` で“元のCLI”を作成・記録、`tmux.set_target`/`tmux.get_target`/`tmux.list_targets`で管理。

Using the MCP Inspector

You can quickly test and explore the server via the Inspector:

```bash
. .venv-mcp/bin/activate
mcp dev run bin/mcp-agentd
```

Targeting
- 明示: `tmux.run({ cmd, target: "session:win.pane" })`
- キー: `tmux.bootstrap({ session, window, key })` → `tmux.run({ cmd, target_key: "key" })`
- Auto: `tmux.run({ cmd })`（省略時にauto）
- Self: `tmux.run({ cmd, target: SELF_PANE })` も可能（サーバをtmux内で起動している場合）

Tools
- `tmux.run(cmd: str) -> { token }`
  - Spawns a new job window via `bin/job-run`.
- `tmux.status(token?: str) -> { ... } | { token: status }`
  - Reads `~/.agentd/<token>.rc` and `~/.agentd/logs/<token>.log` existence.
- `tmux.logs(token: str, tail?: int)`
  - Returns current log text (optionally tail N lines).
- `tmux.stop(token: str)`
  - Kills the job window.

Resources
- Templates: `job://{token}` (application/json), `log://{token}` (text/plain)
  - クライアントはテンプレートに対して `token` を埋めて `read_resource` してください。

Notifications
- 現行のFastMCP APIではサーバ側の `resources/updated` ヘルパが未提供のため、プッシュは未実装です（クライアントは必要に応じてポーリング/再読込を行ってください）。

Troubleshooting
- If logs are empty in MCP, verify the local CLI path is on disk and `bin/` scripts are executable.
- Ensure `~/.agentd/agent_pane` points to a valid tmux pane (re-run `agentd-bootstrap`).
- If Enter doesn’t trigger in your CLI, adjust `AGENTD_SEND_EXTRA_SEQ` (e.g. `Enter Enter`) and try again.
