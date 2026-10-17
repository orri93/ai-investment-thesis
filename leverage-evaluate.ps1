# Set active directory to the script's location
Set-Location $PSScriptRoot

# Activate the Python virtual environment
& ./venv/Scripts/Activate.ps1

# Settings are loaded from .env.

# Execute the Leverage Evaluator Python script (extra arguments are passed through)
python .\leverage-evaluator.py @args
