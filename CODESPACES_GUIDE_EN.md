# Beginner Guide: Run DOAJ_Reviewer Simulation via GitHub Codespaces

This guide is for users with no GitHub experience.
Goal: each colleague runs the simulation independently on their own computer, without private hosting.

## 1. What you need

- A GitHub account (free).
- A modern web browser (Chrome, Edge, Firefox, Safari).
- Stable internet connection.

## 2. Create a GitHub account (if you do not have one)

1. Open `https://github.com/signup`.
2. Enter your email, password, and username.
3. Complete verification steps.
4. Verify your email address.
5. Sign in to GitHub.

## 3. Open the DOAJ_Reviewer repository

1. Go to:
   - `https://github.com/ikhwan-arief/DOAJ_Reviewer`
2. Confirm you can see repository files such as `README.md`.

## 4. Create your own Codespace

1. Click the green `Code` button.
2. Open the `Codespaces` tab.
3. Click `Create codespace on main`.
4. Wait until the browser-based editor loads.

Important:

- Each person should create their own Codespace.
- Do not share one Codespace for all testers.

## 5. Start the simulation server

In Codespaces, open `Terminal` and run:

```bash
PYTHONPATH=src python3 -m doaj_reviewer.sim_server --host 0.0.0.0 --port 8787
```

Expected success message:

```text
DOAJ Reviewer Simulation server running on http://0.0.0.0:8787
```

## 6. Open the simulation page

1. In Codespaces, open the `Ports` panel.
2. Find port `8787`.
3. Click `Open in Browser`.
4. The simulation UI opens in a URL like:
   - `https://<codespace-name>-8787.app.github.dev`

Notes:

- This URL is tied to your Codespace session.
- If the Codespace stops or sleeps, the URL stops working.

## 7. Use the simulation

1. Fill in required journal URLs in the form.
2. Click `Run simulation`.
3. Review outputs:
   - `pass`
   - `fail`
   - `need_human_review`
4. Open generated artifacts if needed.

## 8. Quick health check

If the page does not open, run:

```bash
curl -sS http://127.0.0.1:8787/api/health
```

Expected result:

```json
{"ok": true}
```

## 9. Common issues and fixes

1. `HTTP ERROR 502`
- Cause: server is not running.
- Fix: return to terminal and run the server command again.

2. Port `8787` is not visible
- Cause: app did not start.
- Fix: restart server command, then refresh `Ports`.

3. `No module named doaj_reviewer`
- Cause: wrong directory or missing `PYTHONPATH`.
- Fix: run command from repo root and include `PYTHONPATH=src`.

4. Codespace stopped automatically
- Cause: idle timeout.
- Fix: reopen Codespace and rerun the server command.

## 10. End your session properly

1. Stop server in terminal with `Ctrl + C`.
2. Stop the Codespace to save usage quota.

## 11. Team testing recommendation

For stable cross-country testing:

- Share only the repository link:
  - `https://github.com/ikhwan-arief/DOAJ_Reviewer`
- Ask each colleague to follow this guide and run their own Codespace.
- Do not rely on one shared Codespace session.
