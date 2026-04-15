---
name: db-train-controlled-flow
description: Implements a controlled single-agent DB train query flow (intent extraction, normalization, validation, MCP call, response formatting). Use when building or modifying Deutsche Bahn NLQ features, MCP tool routing, station/time normalization, or train-result formatting.
---

# DB Train Controlled Flow

Use this skill for DB train querying. Keep the architecture deterministic and avoid autonomous agent loops.

## Non-Goals (must avoid)

- Do not build multi-agent conversations.
- Do not add ReAct/self-decision loops.
- Do not let the model freely chain tools.

## Required Flow

Follow this exact pipeline:

1. User input (natural language)
2. LLM extracts intent + parameters
3. Resolver normalizes station/time
4. Validation checks completeness; if missing, ask user directly
5. Call DB MCP server
6. LLM formats the final response text

## Responsibility Boundaries

- **Agent layer** (`backend/app/agents/`):
  - Intent extraction/routing only
  - Output structured JSON
- **Tool layer** (`backend/app/tools/db/`):
  - MCP I/O
  - XML/JSON parsing
  - Station aliases / Hbf fallback / encoding fixes
  - Deterministic filtering rules
- **Service layer** (`backend/app/services/deutsche_bahn_service.py`):
  - Orchestrate the controlled sequence only

## Deterministic Rules

- Default to D-Ticket scope: keep `RE/RB/S` only unless explicitly changed.
- Default top-N: `5` when user does not specify.
- For `now` queries: convert to Berlin time and filter by `YYMMDDHHmm >= now`.
- Prefer line display names (`S1`, `RE5`, `RB39`) over run numbers.

## Data Processing Reference

- See `reference.md` for the authoritative normalization, validation, and parsing rules.

## Validation Contract

Before MCP call, require:

- `origin`
- `destination`
- either:
  - `time_mode=now`, or
  - `date(YYMMDD)` + `hour(HH)`

If any required field is missing, return a concise clarification question instead of guessing.

## Prompt Contract (Agent Output)

Router agent should output JSON only:

```json
{
  "mcp_tool": "getPlannedTimetable",
  "origin": "Düsseldorf",
  "destination": "Duisburg",
  "time": { "mode": "now", "date": null, "hour": null, "minute": null },
  "limit": 5,
  "month_ticket_only": true
}
```

## Change Checklist

- [ ] No new multi-agent behavior introduced
- [ ] No ReAct-style autonomous tool loops introduced
- [ ] Resolver remains deterministic and testable
- [ ] API behavior remains stable for `/api/transport/db/nlq`
- [ ] Debug logs still expose: parsed params, chosen stations, timetable raw, filtered trips

