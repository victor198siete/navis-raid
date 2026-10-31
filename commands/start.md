---
description: Install Navis Raid as a user service and show the address of the dashboard of your Claude Code sessions (http://127.0.0.1:8765 unless you give another port)
argument-hint: "[port]"
allowed-tools: Bash(python3 *)
---

Install Navis Raid as a service of the user: it starts by itself at every login and restarts if it crashes. Do exactly
these steps, in this order, and nothing else:

1. Run `python3 --version`. If `python3` does not exist, tell the user that Navis Raid needs Python 3.9 or newer and stop.
2. Decide the port, `PORT`: the argument the user gave, `$ARGUMENTS`, if it is a whole number between 1 and 65535 and
   nothing else. If it is empty, `PORT` is 8765. If it is anything else, `PORT` is 8765 and you say so in one line
   (never put the text of the argument in a command). Use that same `PORT` in every command and URL below.
3. Run this command with the Bash tool (it installs a launchd agent on macOS or a systemd user unit on Linux, and
   running it again just rewrites it, which points the service to the current version of the plugin):

   ```
   NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" python3 -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --instalar-servicio PORT
   ```

4. Read its output and its exit code.
   - **It worked (exit code 0):** answer in at most four lines:
     - the URL: http://127.0.0.1:PORT
     - that Navis Raid now starts by itself at every login and restarts if it crashes
     - that the data lives in `${CLAUDE_PLUGIN_DATA}`
     - how to remove it: `/navis-raid:stop`
   - **It failed because of permissions** (the output mentions `Operation not permitted`, `PermissionError`,
     `Permission denied` or a similar message, which usually means this session runs in a sandbox that does not allow
     writing outside the project or calling `launchctl`/`systemctl`): do not try again, do not try another way and do
     not change any setting. Tell the user that this has to be done once from outside the sandbox, and give them
     this exact line (with `PORT` filled in), in a code block, to paste in this session with a leading `!` or in their own terminal:

     ```
     NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" python3 -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --instalar-servicio PORT
     ```
   - **The port is already in use (exit code 4):** nothing was installed. Show its message as it is and stop. Do not
     run anything else. The message ends with the command to use another port (`/navis-raid:start <free port>`):
     offer it to the user, but do not run it yourself.
   - **It installed but nothing listens on the port (exit code 5):** the service stays installed. Show its message as
     it is (it includes the last line of `servicio.log`), suggest `/navis-raid:doctor` to see more, and stop. Do not
     try again and do not run anything else.
   - **It failed for any other reason:** show its output as it is and stop.
