# Agent_background_mcp

tmux上で長時間コマンドを非同期実行し、ジョブ終了を“実行元のtmuxペイン（Self）”へ自動通知するMCPサーバです。エージェントがタイムアウトしてもジョブは継続し、進捗はtmuxにアタッチして直接確認できます。終了時はエージェント側に完了通知が返送され、処理をそのまま続行できます。

## Key Features
- タイムアウトに強い非同期実行: エージェントがタイムアウトしても、tmux上のジョブは最後まで走る。
- 進捗の可視化: ジョブは専用ウィンドウで実行。tmuxにアタッチすれば進行度をそのまま見られる。
- 自動復帰通知: 終了時に実行元ペインへ完了メッセージ（Enter付き）を自動送信→エージェントが自動再開。
- 誤配送ゼロ設計: Self（実行元ペイン）に固定して返送。セッション名や環境差に左右されない。
- ログ/追跡性: 各ジョブのログと終了コードをホーム配下（`~/.agentd`）に保存。

## Requirements
- tmux 3.x, Bash
- Python 3.10+（MCPサーバ実行用）
- 任意のMCPクライアント（VS Code / Cursor / Windsurf / Claude Code / Codex など）

## Getting started
まずこのリポジトリをクローンします（MCPサーバはローカルの実行ファイルとして提供）。

```bash
git clone https://github.com/nishimoto265/Agent_background_mcp.git
cd Agent_background_mcp
```

次に、tmux上の“同じペイン”で「MCPサーバ」と「元のCLIエージェント」を起動します。

- 基本（標準）
  - 依存（必要なら。仮想環境は必須ではありません）:
    - `pip install "mcp[cli]" watchfiles`
  - MCPサーバ起動: `./bin/mcp-agentd` （バックグラウンド可: `./bin/mcp-agentd &`）
  - 元のCLI起動: 例 `your-agent-cli --resume <thread-id>`

- 標準設定（多くのクライアントが受け付けるSTDIO定義）
  ```json
  {
    "mcpServers": {
      "agentd": {
        "command": "/absolute/path/to/repo/bin/mcp-agentd",
        "args": []
      }
    }
  }
  ```

### Codex
`~/.codex/config.toml` に以下を追記（パスは実環境に合わせて置換）。

```toml
[mcp_servers.agentd]
command = "/absolute/path/to/repo/bin/mcp-agentd"
args = []
```

Codexを起動すると `tmux.run / tmux.status / tmux.logs / tmux.stop` が利用できます。

### Claude Code
CLIで登録:

```bash
claude mcp add agentd /absolute/path/to/repo/bin/mcp-agentd
```

プロジェクト共有にしたい場合:

```bash
claude mcp add --scope project agentd /absolute/path/to/repo/bin/mcp-agentd
```

### VS Code / Cursor / Windsurf（手動）
MCP設定から「ローカルSTDIOサーバ」を追加:
- Name: `agentd`
- Command: `/absolute/path/to/repo/bin/mcp-agentd`
- Args: （空）

## How to use（tmux上で運用）
1) tmuxを起動/アタッチ（例: `tmux new -s mywork`）

2) 同じペインで起動
- MCPサーバ: `./bin/mcp-agentd &`
- 元CLI: 例 `your-agent-cli --resume <thread-id>`

3) ジョブ投入（Self専用: 送信先は常にこのペイン）
- 即時終了の確認: `./bin/job-run ":"`
- 進捗付き短時間ジョブ: `./bin/job-run "echo '[notify] start'; sleep 1; exit 0"`
- MCPから: `tmux.run({ "cmd": "echo '[notify] hi'; sleep 1; exit 0" })`

完了すると、このペインに `"[notify] job <token> done rc=<rc> timeout=<0|1>"` が表示され、エージェントは手作業ゼロで続行します。進行中の様子は tmux のウィンドウ切替（Ctrl+b → w 等）で確認できます。

## Notes（ログ/終了コード）
- 終了コード: `~/.agentd/<token>.rc`
- ログ: `~/.agentd/logs/<token>.log`
- 宛先（Self）記録: `~/.agentd/<token>.target`

