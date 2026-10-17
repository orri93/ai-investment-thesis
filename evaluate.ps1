# Set active directory to the script's location
Set-Location $PSScriptRoot

# Activate the Python virtual environment
& ./venv/Scripts/Activate.ps1

# Settings are loaded from .env.

# Execute the main Python script (extra arguments are passed through)
python main.py @args
