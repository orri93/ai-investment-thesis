#!/bin/bash

if [ -z "$1" ]; then
	echo "Usage: ./generate-example.sh <draft-thesis-file>"
	exit 1
fi

# Set active directory to the script's location
cd "$(dirname "$0")"

# Activate the Python virtual environment
source ./venv/bin/activate

# Set environment variables
# Replace 'your_openai_api_key' with your actual OpenAI API key
export OPENAI_API_KEY="your_openai_api_key"

# Execute the thesis generator script
# Pass the draft thesis file path as script argument
python thesis-generator.py "$1"
