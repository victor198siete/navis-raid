---
description: Stop Navis Raid and remove its user service (it will no longer start at login)
allowed-tools: Bash(python3 *)
---

Stop Navis Raid and remove its service. Do exactly these steps, in this order, and nothing else:

1. Run this command with the Bash tool (it stops the launchd agent or systemd user unit and deletes its file; if there
   is no service, it says so and nothing else happens):

   ```
   NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" python3 -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --quitar-servicio
   ```

2. Read its output and its exit code.
   - **It worked (exit code 0):** answer in at most two lines: Navis Raid is stopped and will no longer start at login
     (or that there was no service to remove, if that is what it said), and that `/navis-raid:start` installs it again.
   - **It failed because of permissions** (the output mentions `Operation not permitted`, `PermissionError`,
     `Permission denied` or a similar message, which usually means this session runs in a sandbox): do not try again,
     do not try another way and do not change any setting. Tell the user that this has to be done once from outside
     the sandbox, and give them this exact line, in a code block, to paste in this session with a leading `!` or in
     their own terminal:

     ```
     NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" python3 -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --quitar-servicio
     ```
   - **It failed for any other reason:** show its output as it is and stop.
