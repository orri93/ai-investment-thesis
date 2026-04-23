# Set active directory to the script's location
Set-Location $PSScriptRoot

# Activate the Python virtual environment
& ./venv/Scripts/Activate.ps1

# Set environment variables
# Replace 'your_openai_api_key' with your actual OpenAI API key
$env:OPENAI_API_KEY = "your_openai_api_key"

# Replace 'your-email@example.com' with your actual email address
$env:SEC_USER_AGENT = "ai-investment-thesis/1.0 your-email@example.com"

# Execute the Leverage Evaluator Python script
python .\leverage-evaluator.py
