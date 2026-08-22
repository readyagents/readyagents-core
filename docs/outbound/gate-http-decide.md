# ReadyAgents Gate — signed HTTP decide

When an approval node pauses, core writes the run and can POST outbound (`on_pause_url`). Core does **not** listen. ReadyAgents Gate (example: `examples/packs/hitl_gate.py`) accepts **one signed HTTP POST** and maps it to the shipped `readyagents decide` / `resume` path.

```bash
readyagents run examples/approval_gate.yaml          # exit 2, paused
# POST HMAC-SHA256 body to the Gate handler (header X-ReadyAgents-Signature)
# body: {"run_id":"<id>","node_id":"gate","decision":"approve"}
```

A valid signature resumes the run (`approval_gate ok`). An unsigned or forged signature leaves the run paused.

**Implementation CTA:** if you want signed HTTP decide wired onto your own approval workflow (payload schema, secret rotation, one-shot or pack listener), open a GitHub issue titled “Gate HTTP decide — implementation” on [readyagents-core](https://github.com/readyagents/readyagents-core) with a short description of the workflow file and who should be allowed to POST.
