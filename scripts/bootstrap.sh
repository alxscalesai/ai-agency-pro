#!/usr/bin/env bash
set -e
cp -n .env.example .env || true
echo "Bootstrap complete. Edit .env, then run: docker compose up --build"
