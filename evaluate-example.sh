#!/bin/bash

# Set active directory to the script's location
cd "$(dirname "$0")"

# Activate the Python virtual environment
source ./venv/bin/activate

# Set environment variables
# Replace 'your_openai_api_key' with your actual OpenAI API key
export OPENAI_API_KEY="your_openai_api_key"

# Replace 'your-email@example.com' with your actual email address
export SEC_USER_AGENT="ai-investment-thesis/1.0 your-email@example.com"

# Execute the main Python script
python main.py
