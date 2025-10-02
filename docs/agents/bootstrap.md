# Bootstrap Pipeline

- The Start button verifies WSL access, confirms the Codex CLI is installed, ensures the conversation directory exists, writes the default configuration, and runs a health check prompt.
- Health check stdout and stderr are streamed into the conversation pane so problems are visible to the user.
- Failures leave the worker idle without freezing the UI, allowing retries after the underlying issue is resolved.
