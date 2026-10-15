param(
	[Parameter(Mandatory = $true)]
	[string]$DraftThesisFile
)

# Set active directory to the script's location
Set-Location $PSScriptRoot

# Activate the Python virtual environment
& ./venv/Scripts/Activate.ps1

# Configuration
# Settings (OPENAI_API_KEY, OPENAI_MODEL) are read from .env;
# copy .env.example to .env and fill in your values.

# Execute the thesis generator script
# Pass the draft thesis file path as script argument
python thesis-generator.py $DraftThesisFile
