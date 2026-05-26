# Windows Background Launch

Use this when running the app on your PC and you do not want a terminal window to stay open.

## Start

Double-click:

```text
start_app_hidden.vbs
```

or run:

```powershell
.\start_app.bat
```

The server starts hidden on:

```text
http://localhost:8001
```

Logs are written to:

```text
logs/server-8001.out.log
logs/server-8001.err.log
logs/launcher.log
```

## Stop

Run:

```powershell
.\stop_app.bat
```

The app keeps working after you close the terminal or browser, but only while the hidden Python server process is still running. If you restart Windows or run `stop_app.bat`, start it again.
