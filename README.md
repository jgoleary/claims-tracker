# Claims Tracker

Local web app to track OON medical claims submitted to Anthem.

## Install (macOS)

You need only macOS and an internet connection — no developer tools.

**Option 1 — one command (recommended).** Open Terminal and paste:

```bash
curl -fsSL https://github.com/jgoleary/claims-tracker/releases/latest/download/bootstrap.sh | bash
```

**Option 2 — download first.** Download `claims-tracker.tar.gz` from the
[latest release](https://github.com/jgoleary/claims-tracker/releases/latest),
double-click to unpack, then in Terminal type `bash ` (with a trailing space),
**drag the unpacked `deploy/install.sh` into the Terminal window** to fill in its path,
and press Return.

Either way the installer downloads everything it needs, asks for your Anthem login
(saved only to the macOS Keychain), and opens the app at <http://localhost:8000>. The
first claims refresh opens a browser window so you can complete Anthem's multi-factor
login once.

> Don't double-click `install.sh` in Finder — run it through `bash` as shown so macOS
> doesn't block it.

## Uninstall

```bash
bash ~/claims-tracker/deploy/uninstall.sh
```

This stops the background agents. Your data and saved credentials are left untouched;
the script prints how to remove them completely.

## Updating

Re-run the install command above — it updates an existing install in place.

## Development

> Running the app as a user? See **Install (macOS)** above. The steps below are for
> working on the code; the full manual/from-source setup lives in [INSTALL.md](INSTALL.md).

### Backend
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest
uvicorn app.main:app --reload  # after Plan 2
```

### Frontend
```bash
cd frontend
npm install && npm run dev  # after Plan 3
```

### Automation
```bash
cd automation
python fetch_all.py  # prompts for credentials, opens Chromium
```
