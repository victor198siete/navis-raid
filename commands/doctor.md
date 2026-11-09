---
description: Run the read-only Navis Raid diagnostic (what it found on this machine) and the state of its service
allowed-tools: Bash(python3 *), Bash(py *), Bash(python *)
---

Run the Navis Raid diagnostic. Do exactly this and nothing else:

1. Find the Python command, `PY`. Run `python3 --version`; if it fails, prints nothing or prints a version older
   than 3.9, run `py -3 --version`, and if that fails too, `python --version`. `PY` is the first of `python3`,
   `py -3` and `python` that prints Python 3.9 or newer (on Windows `python3` is usually missing or only points to the
   Microsoft Store, and `py` is the Python launcher). If none does, tell the user that Navis Raid needs Python 3.9 or
   newer and stop. Use that same `PY` in every command below, written in place of `PY`.
2. Run this command with the Bash tool:

   ```
   NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" PY -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --doctor
   ```

3. Then run this one, which says whether Navis Raid is installed as a service and where it points:

   ```
   NAVIS_RAID_DATA="${CLAUDE_PLUGIN_DATA}" PY -B "${CLAUDE_PLUGIN_ROOT}/oficina.py" --estado-servicio
   ```

4. Show the output of both exactly as it is, in a code block each, without summarizing, translating or adding
   comments. If a command failed, show its error as it is.
