#!/bin/bash

# Set active directory to the script's location
cd "$(dirname "$0")"

# Activate the Python virtual environment
source ./venv/bin/activate

# Settings are loaded from .env.

# Execute the main Python script (extra arguments are passed through)
python main.py "$@"
