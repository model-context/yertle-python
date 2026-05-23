# Example prompts

A starting library of questions yertle-sre handles well. Add your own as you
discover what works.

## Architecture exploration

- "What organizations do I have in Yertle?"
- "List the top-level nodes in my org."
- "Show me the architecture tree."
- "What does the `payments-api` node depend on?"
- "Which nodes have the `team:platform` tag?"

## AWS state

- "Are any CloudWatch alarms firing in us-east-1?"
- "Describe EC2 instances tagged `Environment=prod` in us-west-2."
- "What CloudFormation stacks exist in us-east-1?"
- "Show me the most recent log events from `/aws/lambda/payments-api`."

## GitHub state

- "List open pull requests in `model-context/yertle-cli`."
- "What's the status of PR #42 in `model-context/yertle`?"
- "Show me failed workflow runs in `model-context/yertle-cli` from the last day."

## Cross-source (the interesting kind)

- "Given my Yertle architecture, which AWS resources back the `api` node, and
  are any of them alarming?"
- "What changed in GitHub recently that could explain alarms on the
  `checkout-service` node?"
- "For each node tagged `team:platform`, summarize its open PRs."

## How the agent answers

The agent has three tools — one read-only runner per CLI: `yertle_run`,
`aws_run`, `gh_run`. Any read-only invocation of any of those CLIs works:

- "What RDS instances do I have in us-west-2?" → `aws_run` with
  `rds describe-db-instances`.
- "What releases has `model-context/yertle` published?" → `gh_run` with
  `release list`.
- "Show me the raw `yertle about` output." → `yertle_run` with `about`.

Destructive invocations (anything that isn't a read-only `describe-*` /
`list-*` / `get-*` / etc., or any `gh` mutation, or `yertle login` / `auth`)
are refused before they reach the CLI.

## Tips

- Name nodes/components by their Yertle title or short ID. The agent will
  resolve them via `yertle_run(["nodes", "<id-or-name>"])` to find AWS /
  GitHub identifiers attached as node attributes.
- Be specific about region for AWS questions — the agent won't guess.
- Use `--verbose` to see which tools are being called.
- Use `repl` for follow-ups: ask a broad question, then drill in.
