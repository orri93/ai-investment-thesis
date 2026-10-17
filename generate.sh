#!/bin/bash

if [ -z "$1" ]; then
	echo "Usage: ./generate.sh <draft-thesis-file>"
	exit 1
fi

# Set active directory to the script's location
cd "$(dirname "$0")"

# Activate the Python virtual environment
source ./venv/bin/activate

# Settings are loaded from .env.

# Execute the thesis generator script
# Pass the draft thesis file path as script argument
python thesis-generator.py "$1"
