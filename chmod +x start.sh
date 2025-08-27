#!/usr/bin/env bash
set -e

if [ "$1" = "build" ]; then
    pip install -r requirements.txt
elif [ "$1" = "start" ]; then
    python main.py
fi
