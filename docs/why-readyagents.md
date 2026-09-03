# Why ReadyAgents?

MCP connectivity is not durable orchestration.

This page records three public reports about gaps between MCP wiring and durable
workflow execution, and states plainly what ReadyAgents 0.8.2 does and does not do
about each one. Each verdict is about our own software only.

## Human-in-the-loop cannot park over the MCP surface

Source: [langchain-ai/langgraph issue 8725](https://github.com/langchain-ai/langgraph/issues/8725)

> A graph that calls `interrupt()` cannot park — there is nowhere to persist the pending state… Any HITL flow is therefore unreachable through the MCP surface.

ReadyAgents 0.8.2: PARTIAL — we persist after each node and resume paused runs, but mcp serve is synchronous stdio with no async task handle and no hosted recovery.

## A long workflow can outlive the call

Source: [n8n community thread on long-running workflows with native MCP](https://community.n8n.io/t/handling-long-running-workflows-with-native-mcp-controlling-ai-response-behavior/230035)

> Ask: “Part 2 of my workflow could take 2-3 minutes… I'm hitting the 60-second MCP timeout limit.”
>
> Reply: “No built-in alternative exists yet.”

ReadyAgents 0.8.2: NO for the networked gap — we checkpoint long runs locally but expose no task-handle or poll API and no always-on worker.

## A tool cannot ask a question mid-call

Source: [MCP Python SDK troubleshooting: no back-channel for server-initiated requests](https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/troubleshooting.md#mcperror-cannot-send-elicitationcreate-this-transport-context-has-no-back-channel-for-server-initiated-requests)

> “The modern protocol has no server-initiated requests at all, so the server refuses before anything is sent.”
>
> “Cannot send 'elicitation/create': this transport context has no back-channel for server-initiated requests.”

ReadyAgents 0.8.2: PARTIAL — our approval node plus persisted pause and later decide/resume sidesteps it at the workflow layer; we do not restore protocol elicitation.
