#!/bin/bash

if [ -z "$1" ]; then
	echo "Usage: ./generate-example.sh <draft-thesis-file>"
	exit 1
fi

# Set active directory to the script's location
cd "$(dirname "$0")"

# Activate the Python virtual environment
source ./venv/bin/activate

# Configuration
# Settings (OPENAI_API_KEY, OPENAI_MODEL) are read from .env;
# copy .env.example to .env and fill in your values.

# Execute the thesis generator script
# Pass the draft thesis file path as script argument
python thesis-generator.py "$1"
