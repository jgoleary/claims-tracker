# Claims Tracker

Local web app to track OON medical claims submitted to Anthem.

## Development

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
