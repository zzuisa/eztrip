## Data processing (authoritative rules)

This file documents the deterministic data-processing rules used by the DB train “controlled flow”.
Keep these rules stable; change them deliberately and bump `policy_version` when behavior changes.

### 1) Time handling

- **Timezone**: interpret “now/现在/目前” using `Europe/Berlin`.
- **Scheduled input**: accept date formats:
  - `YYMMDD` (preferred internal)
  - `YYYYMMDD`
  - `YYYY-MM-DD`
- **Normalization**:
  - Date is normalized to `YYMMDD`.
  - Hour is normalized to `HH` (00–23).
- **Now filter**:
  - Compute `min_departure_time = YYMMDDHHmm` at request time.
  - Filter departures where `departure_time >= min_departure_time`.

### 2) Station resolution

Resolver is deterministic (no LLM guessing):

- **Chinese aliases / abbreviations** (examples):
  - `杜塞尔多夫/杜塞/杜赛` → `Düsseldorf`
  - `杜伊斯堡/杜伊/杜堡` → `Duisburg`
- **Hbf default**:
  - When user does not specify `Hbf/Hauptbahnhof`, search is expanded with:
    - `<query> Hbf`
    - `<query> Hauptbahnhof`
  - When choosing among multiple candidates, prefer `... Hbf`.
- **Encoding repair (mojibake)**:
  - If inputs contain common mojibake markers (e.g. `Ã`, `æ`, `ç`, `å`),
    attempt `latin1 -> utf-8` repair before alias matching.

### 3) MCP tool usage

- **Allowed tools** are enforced by server policy (`backend/app/policies/db_train_controlled_flow.json`).
- Default tool is `getPlannedTimetable`.
- Station lookup uses `findStations`.

### 4) Timetable parsing

- MCP may return **XML** for timetables.
- The parser converts XML into structured `DbTrip` items.
- **Train name display**:
  - Prefer line display names: `S1`, `RE5`, `RB39`
  - Do not expose run-number-only labels (e.g. `S 31173`) for S/RE/RB.

### 5) Filtering + truncation

- Default scope is Deutschlandticket (“month ticket”) style:
  - keep `RE/RB/S` only
- Truncate to top-N (`default_limit`), default **5**.

### 6) Validation (“ask instead of guessing”)

Before calling MCP, require:

- origin
- destination
- time_mode
- and if `time_mode=scheduled`, require `date + hour`

If missing, return a single concise clarification question.

