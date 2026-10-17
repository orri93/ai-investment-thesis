param(
	[Parameter(Mandatory = $true)]
	[string]$DraftThesisFile
)

# Set active directory to the script's location
Set-Location $PSScriptRoot

# Activate the Python virtual environment
& ./venv/Scripts/Activate.ps1

# Settings are loaded from .env.

# Execute the thesis generator script
# Pass the draft thesis file path as script argument
python thesis-generator.py $DraftThesisFile
