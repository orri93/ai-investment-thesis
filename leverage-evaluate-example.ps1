# Set active directory to the script's location
Set-Location $PSScriptRoot

# Activate the Python virtual environment
& ./venv/Scripts/Activate.ps1

# Configuration
# Settings (OPENAI_API_KEY, SEC_USER_AGENT, OPENAI_MODEL) are read from .env;
# copy .env.example to .env and fill in your values.

# Execute the Leverage Evaluator Python script (extra arguments are passed through)
python .\leverage-evaluator.py @args
