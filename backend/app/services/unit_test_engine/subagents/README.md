# Unit Test Subagents

These subagent definitions were generated with `qodercli` `agent-creator` from:

```text
/d/WorkPlace/Learning/hermes-place/WorkPlace/WorkPlace/claudeCode/subagent-maker
```

They are specification assets for the next Agentic unit-test runtime iteration.
They are not wired into the execution path yet.

Runtime constraints:

- `TestManagerAgent` remains the orchestration and decision core.
- Code review stays in the outer pipeline; subagents may only read `code_review_result`.
- Skills may come from project `skills/` and `AI_DEVOPS_SKILLS_ROOTS`.
- `.qoder/skills` must not be used as a runtime skill source.
- Test generation and repair may write only test files, never production code.
