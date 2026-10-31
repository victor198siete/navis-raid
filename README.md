# Navis Raid

A local, pixel-art dashboard for your Claude Code sessions. It draws a building with floors, one cubicle per session,
the sub-agents each session has handed work to, a rooftop where idle agents hang out, and an estimate of how much of
your plan quota you have used.

It reads the transcripts Claude Code already keeps on your disk (`~/.claude/projects/`, or `CLAUDE_CONFIG_DIR` if you
set it) and, on macOS, the desktop app's session files when they exist. It never calls a model (zero tokens; the optional chat is the one exception, see Privacy), it is
plain Python 3 with no dependencies, and it serves only on `127.0.0.1`.

## Requirements

- Python 3.9 or newer (tested with the 3.9 that ships with macOS and with 3.14). 3.8 is not tested.
- macOS or Linux, with Claude Code installed and used at least once (there must be transcripts to read). Windows
  is not supported yet, only because it has not been tested.
- The Claude desktop app is optional. If it is installed on macOS, Navis Raid also uses its session titles, pinned
  sessions, scheduled tasks and sidebar groups (each group becomes a floor).

## Install as a Claude Code plugin

This repository is both a Claude Code plugin and a one-plugin marketplace. In a Claude Code session:

```text
/plugin marketplace add victor198siete/navis-raid
/plugin install navis-raid@navis-raid
/navis-raid:start
```

`/plugin install` opens the plugin's details so you can pick a scope; after installing, run `/reload-plugins` if Claude
Code says a reload is needed. `/navis-raid:start` installs Navis Raid as a **user service** (a launchd agent on macOS,
a systemd user unit on Linux), so it starts by itself at every login and restarts if it crashes, and tells you the
address, <http://127.0.0.1:8765>. `/navis-raid:start [port]` takes an optional port (8765 by default). If something else
already listens on that port (for example a Navis Raid you started by hand), it installs nothing, says so right away and
suggests the first free port after it, for example `/navis-raid:start 8766`; it does not run that command by itself.
If it installs but nothing listens on the port within about 5 seconds (for example the service crashes on start),
it says so, shows the last line of `servicio.log` and points to `/navis-raid:doctor`; the service stays installed.
`/navis-raid:stop` stops it and removes the service. `/navis-raid:doctor` prints the
read-only diagnostic (`--doctor`, see Troubleshooting) followed by the state of the service (`--estado-servicio`).

- **If your session runs in a sandbox** it may not be allowed to write the service file or to call `launchctl` /
  `systemctl`. Then `/navis-raid:start` does not insist: it prints one line with the paths already filled in, and
  you paste it once, with a leading `!` in the session or in your own terminal:

  ```bash
  NAVIS_RAID_DATA="$HOME/.claude/plugins/data/<id>" python3 -B "$HOME/.claude/plugins/cache/<marketplace>/<plugin>/<version>/oficina.py" --instalar-servicio 8765
  ```
- **After updating the plugin, run `/navis-raid:start` again.** The service points to the plugin's folder of that
  moment, which Claude Code replaces on every update; running it again rewrites the service so it points to the new one.
  `--doctor` flags a service whose `oficina.py` no longer exists.
- **On Linux,** a user service keeps running after you log out only if lingering is on for your account
  (`loginctl enable-linger`); otherwise it runs from login to logout.

- **Where the state lives:** in the plugin's data folder (`~/.claude/plugins/data/<id>/`, the folder Claude Code
  calls `CLAUDE_PLUGIN_DATA`), not in the plugin's own folder, which changes with every update. The commands pass it
  to Navis Raid as `NAVIS_RAID_DATA`. Your `config.json` and `pisos.json` go there too (see Data folder). Claude Code
  deletes that folder when you uninstall the plugin from its last scope.
- **Cost:** running `/navis-raid:start`, `/navis-raid:stop` or `/navis-raid:doctor` spends a few tokens, because Claude runs the command.
  The dashboard itself spends none: once the server is up it never calls a model.
- **Without the plugin:** it works the same. Clone or copy this folder and follow Quick start.

## Quick start

```bash
cd path/to/oficina        # the folder that contains oficina.py
python3 oficina.py --serve 8765
```

Then open <http://127.0.0.1:8765/>. The page regenerates on every load and refreshes itself every few seconds.
Stop the server with Ctrl+C.

The file names and some folder names are in Spanish (`oficina` = office, `pruebas` = tests, `bitacora` = log); the
interface itself can be shown in English (see Language).

The data folder must be writable: Navis Raid writes `index.html`, `estado.json` and a `bitacora/` log there (next to
the script by default; see `NAVIS_RAID_DATA` under Configuration).

## Commands

| Command | What it does |
|---|---|
| `python3 oficina.py` | Generates `index.html` and `estado.json` once and prints a summary in the terminal. |
| `python3 oficina.py --watch N` | Regenerates every `N` seconds (default 5) and redraws the summary in the terminal. Ctrl+C stops it. |
| `python3 oficina.py --serve PORT` | Serves the page on `http://127.0.0.1:PORT/` (default port 8765) and regenerates it on each request. |
| `python3 oficina.py --solo-terminal` | Ignores the desktop app's files; the session list comes only from the transcripts. Combine it with `--serve` or `--watch`. Also set by `NAVIS_RAID_SOLO_TERMINAL=1`. |
| `python3 oficina.py --compacto` | Draws the scene at a smaller scale. Combine it with the other options. |
| `python3 oficina.py --doctor` | Read-only diagnostic of what was found on this machine (see Troubleshooting). Also accepted as `doctor`. |
| `python3 oficina.py --instalar-servicio [PORT]` | Installs Navis Raid as a user service that serves on `PORT` (default 8765): `~/Library/LaunchAgents/navis-raid.plist` loaded with `launchctl` on macOS, `~/.config/systemd/user/navis-raid.service` enabled with `systemctl --user` on Linux. It starts at every login and restarts after a crash, not after a clean exit. It passes `NAVIS_RAID_DATA` and, if they are set and not empty in the terminal where you run it, `CLAUDE_CONFIG_DIR`, `NAVIS_RAID_CONFIG` and `NAVIS_RAID_SOLO_TERMINAL` (`--estado-servicio` shows which ones). If the port is already in use the service does not start, does not retry, and exits with 0 after writing one line to `servicio.log` (see Troubleshooting). If something else already listens on `PORT`, it installs nothing and exits with 4, suggesting another port. If the service is installed but nothing listens after 5 seconds, it exits with 5 (the service stays installed). A path or variable that contains a line break is refused (exit code 2), because it would inject lines into the systemd unit. Running it again rewrites the file, so it also repoints the service after an update. |
| `python3 oficina.py --quitar-servicio` | Stops the service and deletes its file. If there is none, it says so and exits with 0. It only tolerates "it was not loaded" (`launchctl bootout` exit code 3 or 113; `systemctl --user disable --now` saying the unit does not exist). With any other failure it prints the error, **keeps the file** and exits with a non-zero code, so it never says "removed" for a service that may still be running. |
| `python3 oficina.py --estado-servicio` | Says whether the service is installed, where its file is, which `oficina.py` and which data folder it points to (and whether that `oficina.py` still exists), which of the variables above it carries (only the ones that are set), whether something is listening on its port, and, if nothing listens and the last line of `servicio.log` is the "port already in use" notice, that line. |

**Clock out button.** The page that `--serve` delivers has a **Clock out** button in the header («Horario de salida» in
Spanish), next to the quota meter. After you confirm, it stops the server: the process exits with code 0, so a
launchd or systemd service is not restarted until your next login (or until you run `/navis-raid:start` again), and a
server started from a terminal simply ends. The page then shows a fixed notice and stops asking for `estado.json`. The
button does not appear on the `index.html` file opened from disk, because that page has no server behind it.

## Configuration

Everything is optional. Without a config file, Navis Raid uses generic defaults: no personal name, no plan boards,
and icons assigned by hashing the session title.

1. Copy `config.ejemplo.json` to `config.json` (same folder) and edit it. Its `_ayuda` key explains every value (in
   Spanish).
2. To use a file elsewhere: `NAVIS_RAID_CONFIG=/path/to/other.json python3 oficina.py --serve 8765`.
3. **Restart the server after any change**: the file is read once, when the program starts.

A broken JSON file, an unknown key or a value of the wrong type does not stop anything: the default is used and the
reason is shown by `--doctor`.

### Data folder

By default everything Navis Raid writes (`index.html`, `tabla.html`, `estado.json`, `bitacora/`, `chat/`) lives next
to the script, and `config.json` and `pisos.json` are read from there. Set `NAVIS_RAID_DATA` to keep all of that in
another folder instead (`~` is expanded; the folder is created when something is first written):

```bash
NAVIS_RAID_DATA=~/navis-raid-data python3 oficina.py --serve 8765
```

The program and `fuentes/` stay where they are. Without `NAVIS_RAID_CONFIG`, the default config file becomes
`$NAVIS_RAID_DATA/config.json`; with it, that variable wins, as before. `--doctor` prints which folder is in use and
marks it as a failure if it cannot be written. When the chat is on, the message sent to the central session carries
`--datos <folder>` in the `responder.py` command, so its reply lands in the same folder. A page opened straight from
a data folder different from the script's loads the fonts from the script's `fuentes/` through an absolute `file://`
URL (some browsers refuse fonts from outside the page's own folder; with `--serve` this does not apply). The page
still makes no network requests. `afk.py`, the author's own script, keeps using the script's folder.

### Floors

When the desktop app has no sidebar groups, the floors come from `pisos.json` (in the data folder: next to the script by default). Start from the
example: `cp pisos.ejemplo.json pisos.json`, then edit it. Floors go from the ground floor up; each one lists folder or
title fragments (case-insensitive) and the first floor that matches wins; a floor with no list collects everything else.
The server rereads the file on every refresh. Without `pisos.json`, everything goes on a single floor.

| Key | What it does | Default |
|---|---|---|
| `nombre_usuario` | Name of whoever attends the sessions ("waiting for ..."). | `""` (shown as "you") |
| `idioma` | Interface language: `"en"`, `"es"` or `null`. | `null` |
| `umbral_relevo_k` | Context size, in thousands of tokens, from which a session is flagged as due for a hand-off (red bar). | `350` |
| `ttl_cache_s` | Pause, in seconds, after which the prompt cache is considered expired. | `3600` |
| `horas_visibles` | Sessions idle for more than this many hours are not drawn. | `48` |
| `modelo_tareas_programadas` | Most expensive model expected in scheduled tasks; a pricier one counts as out of policy in the Cost view. | `"sonnet"` |
| `modelo_agentes_sin_definicion` | Model expected for agents with no definition file of their own. | `"sonnet"` |
| `agentes_con_opus_permitido` | Agent types allowed to use Opus without being flagged. | `[]` |
| `zona_horaria` | Fixed UTC offset for the Cost view, e.g. `{"utc_offset_h": -6, "nombre": "Mexico City"}`. | `null` (machine local time) |
| `raiz_proyectos` | Folder that contains your projects (`~` allowed); stripped from the transcript folder name to name the project. | `"~"` |
| `prefijos_proyecto` | Prefixes removed from project names, for display in the Cost view only. | `[]` |
| `pie` | Footer text of the page. | `"navis raid · cero tokens"` |
| `chat_sesion` | Title of the desktop-app session the optional chat talks to. `null` disables the chat. | `null` |
| `lobby` | Session titles that go to the lobby even if they belong to a sidebar group. | `[]` |
| `sotano` | The sidebar group whose name contains this text goes to the basement. | `"garage"` |
| `familias_iconos` | Icon per project family, e.g. `{"avion": ["travel", "flights"]}`; the first family with a fragment found in the title wins. With no families, the icon is picked by hash; with families but no match, `cubo`. Unknown icons are ignored with a warning. | `{}` |
| `carpeta_planning` | Folder with one subfolder per product (`ROADMAP.md`, ...), relative to `config.json`. `null` means no plan boards. | `null` |

Available icons: avion, huella, camioneta, camara, matraz, portafolio, trofeo, sobre, control, moneda, cubo.

## Language

Set `idioma` in `config.json`:

- `"en"` for English, `"es"` for Spanish.
- `null` (the default) follows the system language: a Spanish locale gives Spanish, anything else gives English.

## Troubleshooting

Claude Code's transcripts and the desktop app's files are internal formats that are not documented and may change
between versions. If something looks wrong or the office is empty, run:

```bash
python3 oficina.py --doctor
```

It only reads. It reports, with a check mark, a warning or a cross for each item:

- whether `config.json` loads, and why not if it does not;
- which Claude Code configuration folder is used (`~/.claude` or `CLAUDE_CONFIG_DIR`);
- how many transcripts it found and how many have activity within the visible window;
- whether the fields it needs (`type`, `timestamp`, `cwd`, `version`, token usage, message content, titles) appear in
  the most recent transcripts, and how many lines it had to skip;
- the Claude Code version seen in the transcripts compared with the version it was tested with (currently 2.1.x). A
  different patch version does not matter; a different major or minor version raises a warning that the format may have
  changed;
- whether the desktop app's files, scheduled tasks and sidebar groups were found (macOS only);
- how many agent definitions exist in the configuration folder;
- whether the `bitacora/` folder exists and is writable;
- if the user service is installed, whether the `oficina.py` and the Python interpreter it points to still exist (they do not
  after a plugin or Python update: run `/navis-raid:start` again), and, if nothing listens on its port and `servicio.log`
  ends with the "port already in use" notice, that notice.

The exit code is 1 only if there is no `projects/` folder and no readable transcripts.

**The service does not start because the port is busy.** With `--serve`, if something already listens on the port, Navis
Raid writes one line to the error output (`port N is already in use; Navis Raid does not start. Free it or reinstall
with another port`) and stops. As a service it exits with 0, so launchd and systemd do not relaunch it in a loop and
`servicio.log` does not grow; in a terminal it exits with 3. `--estado-servicio` and `--doctor` show that line when
nothing listens on the port. Free the port, or run `/navis-raid:start` again with another one (for example
`python3 oficina.py --instalar-servicio 8766`). Since the E8e-4, `--instalar-servicio` checks the port *before* writing
anything: if another process already listens there it installs nothing, prints the first free port after it and exits with 4
(a service that is already installed on that same port is not an obstacle: that is a reinstall). From the command line it also waits up to 5 seconds for something to listen on the port; if nothing does, it exits with 5, leaves the service installed and prints the last line of `servicio.log`.

## Privacy

Navis Raid reads everything Claude Code keeps about your sessions, so this section says exactly what it reads,
what it writes, what it runs and what it connects to. It was written from the code (checked on 27 Oct 2026, with
the Python files in this folder); if you change the code, these statements may stop being true.

### In short

- Everything is local. There is no telemetry, no update check and no connection to the internet. The server
  listens only on `127.0.0.1`.
- Navis Raid itself never calls a model. The one exception in effect is the optional chat: a message you send is a
  turn of the Claude Code session you configured, and that session spends your plan's tokens. The chat is off by
  default.
- It reads all of your Claude Code transcripts, which can contain anything you and Claude have discussed.
- The generated `index.html`, `tabla.html` and `estado.json` contain the text of your requests and your session
  titles (details below). Do not share them, and do not commit them.

### What it reads

All reads are read-only. Nothing is changed, moved or deleted in these places.

| What | Where | When |
|---|---|---|
| Transcripts of every session and sub-agent: `*.jsonl`, plus `<session>/subagents/agent-*.meta.json` | `~/.claude/projects/` (or `$CLAUDE_CONFIG_DIR/projects/`) | Always. Each transcript is read in full the first time and then only what was added; the first and last 256 KB are read to find the title and working folder. The cost log keeps its own read position (see below). |
| Agent definitions (`*.md`; only the `model:` line is used) | `~/.claude/agents/` (or `$CLAUDE_CONFIG_DIR/agents/`), and `.claude/agents/` inside each session's working folder | Always. The file names list your agent roster; the first 4,000 characters of a definition are read to get its `model:` line, for each sub-agent seen. |
| Session titles, pinned flag, working folder, model (`local_*.json`) and scheduled tasks (`scheduled-tasks.json`) | `~/Library/Application Support/Claude/claude-code-sessions/` | Only on macOS, only if the Claude desktop app's folder exists, and not with `--solo-terminal`. |
| Sidebar groups of the desktop app (one key of `claude_desktop_config.json`) | `~/Library/Application Support/Claude/` | Same conditions as the line above. |
| `config.json` (or the file named by `NAVIS_RAID_CONFIG`) | In the data folder (next to the script by default, or `NAVIS_RAID_DATA`) | Once, at start-up, if the file exists. |
| `pisos.json` (floor layout) | In the data folder (next to the script by default, or `NAVIS_RAID_DATA`) | Only when the desktop app has no sidebar groups, if the file exists. |
| `productos.tsv`, `<product>/ROADMAP.md`, the first heading of each note in `<product>/ideas/`, and the number of notes in `<product>/decisions/` | Inside `carpeta_planning` | Only if you set `carpeta_planning`. Off by default. |
| `bitacora/cuota.jsonl` and the daily `bitacora/*.jsonl` files | In the data folder (next to the script by default, or `NAVIS_RAID_DATA`) | If they exist. These are Navis Raid's own files (see below). |
| `chat/hilo.jsonl` | In the data folder (next to the script by default, or `NAVIS_RAID_DATA`) | Only if `chat_sesion` is set. |
| Two optional CSV files of the author's own projects | Two folders above this one (`../../ideas/angular-quest/personas.csv`, `../../visionarios/roster.csv`) | At start-up. They do not exist on other machines and are then ignored; nothing depends on them. |

`raiz_proyectos` is not a place that is scanned: it is only used to shorten the project names that appear in the
transcript folder names.

### What it writes

Everything is written in the data folder (next to the script by default, or the folder named by `NAVIS_RAID_DATA`), and the files below are relative to it. **It never writes inside `~/.claude` (or
`CLAUDE_CONFIG_DIR`) or inside the desktop app's folder, and in normal use it writes nothing outside the data folder.
The one exception is the service definition file listed in the table below, and only if you install the service.**
(The one place where the data folder is under `~/.claude` is when you run it as a plugin: then it is the folder Claude
Code reserves for the plugin, `~/.claude/plugins/data/<id>/`, and nothing else in `~/.claude` is touched.)

| File or folder | Contains | Written by |
|---|---|---|
| `index.html`, `tabla.html`, `estado.json` | The live view: session titles, working-folder paths, the first line of your latest request and of Claude's last reply, a short history (the first line of recent requests, and a one-line summary of recent tool calls such as the command, file path, URL or search query, cut to about 70 characters), the task given to each sub-agent, token counts, and, when `carpeta_planning` is set, product names, roadmap progress, git branch names and the last commit subject. With the chat on, also the chat thread. | Every run, every `--watch` pass and every page load with `--serve`. Each file is written to a temporary file and then renamed into place. |
| `bitacora/YYYY-MM-DD.jsonl` | One line per model call: time, first 8 characters of the session id, session title, project folder name, agent type and id, model, token counts, context size, pause since the previous call. **No message text.** | Only after you have run `python3 bitacora.py --reconstruir` once (see the notes below). |
| `bitacora/.offsets.json`, `bitacora/.lock` | How far each transcript has been read (with the paths of your transcripts); a lock so two copies do not write at once. | Same as above (the folder itself is created on every pass). |
| `bitacora/cuota.jsonl`, `bitacora/relevos.jsonl` | Plan-usage readings and hand-off records. Written only by the helper scripts below, never by `oficina.py`. `cuota.jsonl` lives in the data folder; `relevos.jsonl` is always next to the script, because `afk.py` does not read `NAVIS_RAID_DATA` (if `afk.py` is present, `oficina.py` reads it from there too). | `cuota.py`, `afk.py` |
| `bitacora/respaldo-dedup/` | A copy of the daily files, made before de-duplicating. | Only `python3 bitacora.py --deduplicar` |
| `chat/hilo.jsonl` | The text of each chat message you send and each reply. | The server after a chat message is delivered, and `responder.py`. Only with the chat on. |
| `servicio.log` | What the service prints (the address it serves on, and any error, such as the notice that the port is already in use). Not rewritten: it grows. | The service, once installed |
| `~/Library/LaunchAgents/navis-raid.plist` (macOS) or `~/.config/systemd/user/navis-raid.service` (Linux) — **outside the data folder** | The service definition: the Python interpreter, the path of `oficina.py`, the port, the data folder, `NAVIS_RAID_SERVICIO=1` and a copy of `CLAUDE_CONFIG_DIR`, `NAVIS_RAID_CONFIG` and `NAVIS_RAID_SOLO_TERMINAL` if they were set when you installed it. It runs Navis Raid **at every login** and restarts it after a crash, until you remove it. | Only `--instalar-servicio` (`/navis-raid:start`); `--quitar-servicio` (`/navis-raid:stop`) deletes it |
| `__pycache__/` | Python's own compiled files. | Python |

Notes:

- The cost log stays empty until you run `python3 bitacora.py --reconstruir` once. Until then the folder `bitacora/`
  is created (empty) and nothing else is written to it. After that, every run adds the new calls and deletes daily
  files and plan readings older than five weeks of your plan. `--reconstruir` deletes and rewrites the daily files
  and `.offsets.json` from the transcripts that still exist.
- Files are created with your default permissions (the code never changes them). On a computer shared with other
  accounts, keep this folder where only you can read it.
- The shipped `.gitignore` excludes the generated files, `bitacora/`, `chat/`, `__pycache__/`, `config.json` and
  `pisos.json`: your name and session titles stay out of git. (If you already committed one of them, `.gitignore`
  does not remove it from the index; use `git rm --cached`.)

### What it runs

- `git`, only if you set `carpeta_planning`: in each repository of your products list (and in a session's folder
  when it is a git worktree of one of them), as `git --no-optional-locks -C <repo> status --porcelain=v1 -b`,
  `git --no-optional-locks -C <repo> log -1 --format=%ct%x09%s` and `git --no-optional-locks -C <repo> remote`, each
  with a 5-second timeout and cached for 60 seconds. It reads the branch, the number of changed files, whether the
  branch is ahead, and the last commit subject. `--no-optional-locks` keeps `git status` from refreshing the index,
  so these commands do not write to the repository; git still uses that repository's own configuration.
- `lsof -a -p <pid> -d cwd -Fn`, only when you send a message with the optional chat: it finds which running Claude
  Code process has the working folder of the target session. If `lsof` is missing or cannot run, the message goes to every
  session inbox found (see the chat section).

- `launchctl` on macOS, only with `--instalar-servicio` and `--quitar-servicio`, always on your own user's domain:
  `launchctl bootout gui/<uid>/navis-raid` and `launchctl bootstrap gui/<uid> ~/Library/LaunchAgents/navis-raid.plist`
  (the first one is also run before reinstalling, and its failure is ignored there). When removing, `bootout` is
  tolerated only if the service was not loaded (exit code 3 or 113); any other failure keeps the file and exits non-zero.
- `systemctl --user` on Linux, only with the same two options: `daemon-reload`, `enable --now navis-raid` (plus
  `restart navis-raid` when you install over an existing service), `disable --now navis-raid` (tolerated only if the unit
  does not exist; any other failure keeps the file and exits non-zero) and, after removing, `daemon-reload`.

Nothing else is executed: no shell, no download, no `eval` or `exec`. These commands are run with a list of
arguments, without a shell, and with a 30-second timeout.

### Network

- The server (`--serve`) binds to `127.0.0.1` only, so it is not reachable from other computers. Without `--serve`,
  there is no server at all.
- It answers only `GET /`, `/index.html`, `/tabla.html`, `/estado.json` and the three `/fuentes/*.woff2` font files,
  plus `POST /salida` (the Clock out button) and, with the chat on, `POST /chat`. There is no folder listing, and no
  other file is served.
- It rejects any request whose `Host` header is not exactly `127.0.0.1`, `localhost` or `[::1]` with the server's own
  port. That blocks DNS-rebinding attacks from web pages in your browser.
- Every response carries `Cache-Control: no-store`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY` and
  `Content-Security-Policy: frame-ancestors 'none'`. It sends no CORS headers and does not answer `OPTIONS`.
- The page makes no request to any other host. It loads its fonts from `fuentes/` (Press Start 2P and JetBrains Mono,
  SIL Open Font License 1.1; the license texts are next to the font files) and talks only to the server it came from
  (`estado.json` and, with the chat on, `POST /chat`). The program makes no outgoing connection: none of its files
  opens an internet socket as a client or imports an HTTP client. The only client sockets are the local Unix sockets
  of the optional chat. (The test in `pruebas/servidor.py` connects to a throwaway server on `127.0.0.1`.)

- `POST /salida` stops the server (the Clock out button). It requires exactly what `POST /chat` requires, checked in the
  same order: a `Host` header of its own, the per-run token in `X-Navis-Raid-Token` (compared in constant time),
  `Content-Type: application/json` and, if the browser sends one, a matching `Origin`. Anything else gets 403 and the
  server keeps running. It exists even when the chat is off. A page you did not get from this server cannot call it:
  the token is only in the page that `--serve` delivers.

### The optional chat

- It is **off** unless you set `chat_sesion` in `config.json` to the title of a Claude Code session in the desktop
  app. Without that key the page has no chat box and the server answers `POST /chat` with 404.
- When you type a message, the server finds that session (by title, among the desktop app's sessions), looks for its
  inbox (a Unix socket named `<pid>.sock` in `/tmp/cc-socks`, `/tmp/cc-socks-<uid>` or `/private/tmp/cc-socks`) and
  writes your text into it. The session receives it as if you had typed it, and works on it with its normal tools
  (it can read and edit files and run commands, under that session's own permissions). The message also tells the
  session to answer by running `responder.py`, which appends the reply to `chat/hilo.jsonl`.
- `POST /chat` requires a per-run secret token (kept in memory, never written to disk, and placed only in the page
  served by `--serve`), the header `X-Navis-Raid-Token`, `Content-Type: application/json`, a matching `Origin` if
  the browser sends one, a body of at most 20,000 bytes and a message of at most 4,000 characters.
- The inbox format is taken from text inside the Claude Code binary, not from documentation. It may change or stop
  working with any Claude Code version.

### Known limitations

- **Local programs can use the chat.** While `--serve` runs with the chat on, any program on your computer, and any
  other user account on it, can open `http://127.0.0.1:<port>/`, read the secret token from the page and then send
  text to your configured session, because the token protects against websites, not against other local processes.
  The same text then runs with that session's permissions. This is a known issue (F-002 in
  `auditorias/2026-10-27-E6-servidor.md`) that will be reviewed before the public beta. Until then, leave the chat
  off (the default) if other people or untrusted programs share your computer.
- **The page itself is not password-protected.** While the server runs, any program or user on the same computer can
  read the page and `estado.json`, which contain the data listed under "What it writes".
- **With the chat on and `lsof` unavailable,** the message is written to every Claude Code inbox found, not only the
  target one. Each message carries the target session's id and Claude Code is expected to discard messages that are
  not for it; that behaviour comes from the same undocumented binary text and has not been verified here.
- **Internal formats.** The transcripts and the desktop app's files are internal formats that are not documented and
  may change. Navis Raid skips what it does not understand; see Troubleshooting and `--doctor`.

### Removing it

If you installed the service, remove it first, while the program is still there: `/navis-raid:stop` or
`python3 oficina.py --quitar-servicio`. Otherwise the login item stays behind pointing to nothing, and the system
keeps trying to start it. (`--estado-servicio` tells you whether it is installed; if the program is already gone,
delete `~/Library/LaunchAgents/navis-raid.plist` after `launchctl bootout gui/$(id -u)/navis-raid`, or run
`systemctl --user disable --now navis-raid` and delete `~/.config/systemd/user/navis-raid.service`.)

Delete this folder. That removes the program, its generated pages and everything under `bitacora/` and `chat/`: it
keeps nothing anywhere else. If you set `NAVIS_RAID_DATA`, delete that data folder too (it holds the pages, `bitacora/`
and `chat/`). If you pointed `NAVIS_RAID_CONFIG` at a file elsewhere, delete that file too. Stop
the server first (Ctrl+C). Your Claude Code transcripts and the desktop app's files were never changed.

### Helper scripts

The folder also holds a few scripts. None of them runs on its own: `oficina.py` never starts them, and they act
only when you run them yourself.

| Script | What it does | What it writes |
|---|---|---|
| `bitacora.py` | Command-line access to the cost log: `--reconstruir`, `--deduplicar`. | The files under `bitacora/` described above. |
| `cuota.py` | Reads a plan-usage reading as JSON from standard input (`anotar`) and prints an estimate from it and the cost log. | Appends to `bitacora/cuota.jsonl`; also updates the cost log. |
| `afk.py` | Lists idle sessions that are large and still warm in the cache (`--json`), or records that a hand-off was requested (`anotar`). Listing regenerates `estado.json` first. | `estado.json`, and `bitacora/relevos.jsonl` (time, session id, title and context size), both next to the script (it ignores `NAVIS_RAID_DATA`). |
| `responder.py` | Adds a reply to the chat thread. | Appends to `chat/hilo.jsonl`. |
| `sonda-socket.py` | Sends one test message to a Claude Code inbox socket that you name on the command line, and prints the answer. | Nothing. |
| `costo.py` | Builds the cost summary used by the page; run directly it prints it. | Nothing. |
| `avatar32.py`, `oficina_iso.py` | Drawing code. Run directly, they export sample SVG / HTML previews. | `svg/` (next to the script) and `_preview-iso.html` (in the folder you ran it from). |

`cuota.py`, `afk.py`, `responder.py` and `sonda-socket.py` are made for the author's setup (a central Claude session
that reports usage and receives hand-offs); you can ignore them or delete them. `oficina.py` works without
`afk.py`: if the file is missing, no session is shown as handed off.

## Tests

From this folder, with no dependencies:

```bash
python3 pruebas/configuracion.py   # config: defaults, broken files, values reaching the page
python3 pruebas/duplicados.py      # the log does not repeat entries after losing its read state
python3 pruebas/tolerancia.py      # broken transcripts in a fake CLAUDE_CONFIG_DIR raise no exception
python3 pruebas/idiomas.py         # Spanish and English texts are complete
python3 pruebas/portabilidad.py    # the cost log works without fcntl; git runs with --no-optional-locks
python3 pruebas/servidor.py        # --serve only serves the page, only to localhost, and POST /chat and POST /salida need a token
python3 pruebas/paquete.py         # the folder copied on its own works, also without afk.py, and the page asks the network for nothing
python3 pruebas/datos.py           # with NAVIS_RAID_DATA everything is written in that folder and nothing next to the code
python3 pruebas/servicio.py        # the launchd / systemd service files and commands, with a temporary HOME and a fake runner
```

They work on temporary directories and fake configurations, not on your real transcripts or config. The service test
never touches your real home folder, `launchctl` or `systemctl`.

## Status / roadmap

Beta. It works, but it has been used on one machine only. Still to do before a public release:

- ~~E5 · Self-contained package~~ done (27 Oct 2026): `avatar32.py` and the fonts are bundled, so this folder runs
  copied on its own and the page makes no network requests.
- ~~E6 · Chat off by default~~ done (27 Oct 2026): the chat exists only with `chat_sesion`; `--serve` serves a fixed
  list of files, checks the `Host` header and protects `POST /chat` with a token.
- ~~E7 · Privacy statement~~ done (27 Oct 2026): the Privacy section above lists what is read, written, run and
  connected to, and the known limitations.
- ~~E8 · Installation as a Claude Code plugin~~ done (29 Oct 2026): the repository is a plugin and a marketplace
  (`/plugin marketplace add victor198siete/navis-raid`, see Install as a Claude Code plugin). Installation with `pipx`
  does not exist yet.
- E9 · Beta testing on other machines (Linux, terminal-only).

## License

The code is released under the [MIT License](LICENSE). The bundled fonts in `fuentes/` keep their own SIL Open Font
License 1.1 (the license texts are next to the font files).
