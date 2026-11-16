#!/usr/bin/env bash
# Rebuild the React UI (Next.js static export) into src/app/static, served by FastAPI.
set -euo pipefail
cd "$(dirname "$0")/../frontend"
npm ci --no-audit --no-fund
npm run build
rm -rf ../src/app/static
cp -r out ../src/app/static
echo "UI built into src/app/static"
