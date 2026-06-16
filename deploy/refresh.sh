#!/bin/bash
# Triggers a daily Anthem refresh through the running server.
set -euo pipefail
echo "refresh: starting at $(date)"
curl -fsS -X POST http://localhost:8000/api/automation/run \
  -H 'Content-Type: application/json' -d '{}'
echo
echo "refresh: request accepted at $(date)"
