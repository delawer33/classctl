# classctl — Domain Glossary

## Classroom
A named configuration representing one physical training room. Owns: subnet (CIDR), SSH private key path, and a Step Mapping. Persists a Machine List between sessions.

## Machine
A workstation in a Classroom, identified by IP address and MAC address. Can be added/removed manually or discovered via Discovery. A Machine is considered a target when its checkbox is selected before a Run.

## Discovery
An ARP scan of the Classroom's subnet (via `lan_ip.py`) that returns the current list of live (IP, MAC) pairs. Results are persisted as the Classroom's Machine List. Requires the operator's laptop to be on the classroom subnet.

## Machine List
The persisted set of Machines belonging to a Classroom. Updated by Discovery or by manual add/remove. Shown immediately on load; operator triggers Discovery explicitly to refresh.

## Step
One script in the fixed execution sequence. There are five Steps:
1. Stop VMs
2. Delete VMs
3. Reset host
4. Create VMs
5. Shutdown (optional)

## Step Mapping
The explicit per-Classroom configuration that maps each Step to a specific script filename within the script directory. Stored as part of the Classroom config.

## Pipeline
The ordered sequence of Steps 1–4 (plus optional Step 5) executed against a set of target Machines. Execution order is strictly fixed; Steps cannot be reordered or skipped mid-sequence. The operator may choose which Step to start from.

## Run
A single execution of a Pipeline: a chosen start Step, a set of target Machines, and an optional shutdown flag. One Run at a time; a new Run cannot start while another is active on any Classroom.

## Run Result
The outcome of a Run per Machine per Step: output (full stdout/stderr always captured), and a status derived from output pattern matching (flagged / clean).

## Error Detection
Best-effort: stdout/stderr is always captured for every Step on every Machine regardless of outcome. Lines matching configurable error patterns are highlighted. Exit codes are ignored. When errors are detected on any Machine after a Step completes, the Run pauses and prompts the operator to Retry (failed machines only), Skip & Continue, or Abort.

## Error Patterns
A global, editable set of case-insensitive output substrings used for Error Detection (e.g. `error`, `failed`, `traceback`, `exception`). Applied uniformly across all Classrooms.

## Run Monitor
The UI view during an active Run. Shows a table with one row per target Machine: current status (running / clean / flagged / done) and the last log line. Clicking a row expands the full captured output for that Machine.

## Operator
The single person who runs classctl. Operates from a laptop physically present in the classroom, connected to the classroom subnet. No authentication is required.
