# Updating to a new version

The project lives on GitHub, so updating is one pull. You already have Python and the
dependencies installed.

1. In the PowerShell window where the app is running, press **Ctrl+C** to stop it.
2. Get the latest code and any new dependencies:

```
git pull
.venv\Scripts\pip.exe install -r requirements.txt
```

3. Start it again:

```
.venv\Scripts\python.exe run.py
```

If the page looks unchanged after restarting, your browser is showing a cached copy:
press **Ctrl+Shift+R** to force a reload.

An older copy may still have a `.env` file with an API key in it. Nothing reads it any
more; you can delete it.
