# Beginner Guide: Run DOAJ_Reviewer Simulation via GitHub Codespaces (Updated)

This guide is for non-technical users.
Goal: run the DOAJ Reviewer simulation in GitHub Codespaces without private hosting.

## 1. What changed from the previous guide

- The simulation form includes the latest DOAJ field order.
- New result actions are available: `Reset form`, `Print to PDF`, and `Download text`.
- Flagged checks (`fail` and `need_human_review`) now show `Review URLs` for human follow-up.
- Extra troubleshooting was added for:
  - `HTTP ERROR 502`
  - wrong folder path
  - `Run simulation` button not responding (cache/old JS issue)

## 2. What you need

- A GitHub account (free).
- A modern browser (Chrome, Edge, Firefox, Safari).
- Stable internet connection.

## 3. Open repository and create Codespace

1. Open `https://github.com/ikhwan-arief/DOAJ_Reviewer`.
2. Click `Code` -> `Codespaces` -> `Create codespace on main`.
3. Wait until VS Code in browser is ready.

Important:

- Each tester should create their own Codespace.
- Do not share one running Codespace between multiple people.

## 4. Verify the working directory

In terminal, run:

```bash
pwd
ls
```

You should be inside the `DOAJ_Reviewer` repository root (where `README.md` exists).

If `cd /home/codespace/workspaces/DOAJ_Reviewer` fails, use:

```bash
cd ~/workspaces/DOAJ_Reviewer
```

or manually navigate using the folder shown by `pwd`.

## 5. Start the simulation server

Run:

```bash
PYTHONPATH=src python3 -m doaj_reviewer.sim_server --host 0.0.0.0 --port 8787
```

Expected message:

```text
DOAJ Reviewer Simulation server running on http://0.0.0.0:8787
```

Keep this terminal running.

## 6. Open the simulation UI

1. Open the `Ports` panel in Codespaces.
2. Find port `8787`.
3. Set visibility to `Public` if needed.
4. Click `Open in Browser`.

The URL looks like:

- `https://<codespace-name>-8787.app.github.dev`

## 7. Run a simulation

1. Fill the form with journal URLs.
2. Click `Run simulation`.
3. Review:
   - overall result (`pass`, `fail`, `need_human_review`)
   - per-rule notes
   - `Review URLs (for flagged results)`
4. Optionally use:
   - `Print to PDF`
   - `Download text`
   - `Reset form` for a new case

## 8. Quick health check

If UI is not working, run:

```bash
curl -sS http://127.0.0.1:8787/api/health
```

Expected:

```json
{"ok": true}
```

## 9. Common issues and fixes

1. `HTTP ERROR 502`
- Cause: server is not running or crashed.
- Fix: restart the server command in terminal.

2. `Run simulation` / `Reset form` does nothing
- Cause: old cached UI JavaScript.
- Fix:
  - hard refresh browser (`Ctrl+F5` or `Cmd+Shift+R`)
  - if needed, stop and restart server
  - reopen port URL from Codespaces `Ports` panel

3. `No module named doaj_reviewer`
- Cause: wrong directory or missing `PYTHONPATH=src`.
- Fix: run command from repo root and include `PYTHONPATH=src`.

4. Port `8787` not visible
- Cause: app not started.
- Fix: rerun server command, then refresh the `Ports` panel.

5. Codespace stopped automatically
- Cause: idle timeout/quota.
- Fix: reopen Codespace and rerun the server command.

## 10. Stop server correctly

- In the running terminal, press `Ctrl + C`.

If needed, find and stop by port:

```bash
lsof -i :8787
kill <PID>
```

## 11. Team testing recommendation

For stable cross-country testing:

- Share the repository link:
  - `https://github.com/ikhwan-arief/DOAJ_Reviewer`
- Ask each colleague to run their own Codespace session.
- Do not depend on one shared URL, because Codespaces URLs are session-bound.
