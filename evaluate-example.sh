#!/bin/bash

# Set active directory to the script's location
cd "$(dirname "$0")"

# Activate the Python virtual environment
source ./venv/bin/activate

# Configuration
# Settings (OPENAI_API_KEY, SEC_USER_AGENT, OPENAI_MODEL) are read from .env;
# copy .env.example to .env and fill in your values.

# Execute the main Python script (extra arguments are passed through)
python main.py "$@"
