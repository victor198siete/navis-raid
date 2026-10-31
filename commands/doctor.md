---
description: Run the read-only Navis Raid diagnostic (what it found on this machine) and the state of its service
allowed-tools: Bash(python3 *)
---

Run the Navis Raid diagnostic. Do exactly this and nothing else:

1. Run this command with the Bash tool:

   ```
   NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" python3 -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --doctor
   ```

2. Then run this one, which says whether Navis Raid is installed as a service and where it points:

   ```
   NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" python3 -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --estado-servicio
   ```

3. Show the output of both exactly as it is, in a code block each, without summarizing, translating or adding
   comments. If a command failed, show its error as it is.
