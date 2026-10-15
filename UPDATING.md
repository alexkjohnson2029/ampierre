# Updating to a new version

You already have Python and the dependencies installed, so you don't redo any of that.

1. In the PowerShell window where the app is running, press **Ctrl+C** to stop it.
2. Unzip the new `schematic2breadboard.zip` (right-click → Extract All).
3. Open the new folder until you see `run.py`. Select everything (**Ctrl+A**), copy
   (**Ctrl+C**), then go to your existing project folder and paste (**Ctrl+V**).
   Windows will ask what to do about files that already exist — choose
   **"Replace the files in the destination."**
4. Start it again in PowerShell:

```
.venv\Scripts\python.exe run.py
```

Your `.venv` folder and your `.env` (with the API key) stay where they are — that's why
you copy the new files *over* the old folder instead of starting fresh somewhere else.

If the page looks unchanged after restarting, your browser is showing a cached copy:
press **Ctrl+Shift+R** to force a reload.
