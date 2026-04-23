param(
	[Parameter(Mandatory = $true)]
	[string]$DraftThesisFile
)

# Set active directory to the script's location
Set-Location $PSScriptRoot

# Activate the Python virtual environment
& ./venv/Scripts/Activate.ps1

# Set environment variables
# Replace 'your_openai_api_key' with your actual OpenAI API key
$env:OPENAI_API_KEY = "your_openai_api_key"

# Execute the thesis generator script
# Pass the draft thesis file path as script argument
python thesis-generator.py $DraftThesisFile
