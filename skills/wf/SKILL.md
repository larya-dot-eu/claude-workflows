---
name: wf
description: Controls the Claude-Workflows skin. Use only when the user types /wf.
disable-model-invocation: true
argument-hint: "[on | off | pause | status | help]"
---

The wf hook has already applied `/wf $ARGUMENTS`; its result is in the context just added to this
turn. Do exactly what that result says (usually: confirm the new state to the user in one short
line). Do not start any other work in this turn.
