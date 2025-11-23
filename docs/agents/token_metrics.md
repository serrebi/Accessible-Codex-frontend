# Token Metrics

The frontend parses Codex output to track usage statistics in real time:

- Watches for case-insensitive matches on "Tokens used", "Token usage", and "Context remaining".
- Maintains `tokens_used`, `token_budget`, and `tokens_remaining`, and displays "Tokens used / Remaining / % left" between the output and thinking panels as well as in the history list.
- Updates the assumed context window whenever Codex reports a larger total than previously recorded, allowing the UI to learn the actual capacity.
- Refreshes metrics whenever either the conversation log or thinking pane receives new text, keeping streaming updates consistent across panes.
- Hidden (and removed from tab order) by default; toggle via View → “Show Token Metrics”. The history panel mirrors the same visibility and text.
