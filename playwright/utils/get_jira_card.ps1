param(
    [Parameter(Mandatory = $true)]
    [string]$IssueKey
)

$envPath = ".\.env"
if (-not (Test-Path $envPath)) {
    Write-Error "Could not find .env file at $envPath"
    exit 1
}

# Parse .env file correctly handling values with '='
$envContent = Get-Content $envPath
$jiraEmail = (($envContent -match "^JIRA_EMAIL=" | Select-Object -First 1) -replace "^JIRA_EMAIL=", "").Trim()
$jiraToken = (($envContent -match "^JIRA_API_TOKEN=" | Select-Object -First 1) -replace "^JIRA_API_TOKEN=", "").Trim()
$jiraBaseUrl = (($envContent -match "^JIRA_BASE_URL=" | Select-Object -First 1) -replace "^JIRA_BASE_URL=", "").Trim()

if (-not $jiraEmail -or -not $jiraToken -or -not $jiraBaseUrl) {
    Write-Error "Missing required JIRA configuration in .env"
    exit 1
}

$pair = "${jiraEmail}:${jiraToken}"
$bytes = [System.Text.Encoding]::UTF8.GetBytes($pair)
$base64 = [System.Convert]::ToBase64String($bytes)
$headers = @{
    "Authorization" = "Basic $base64"
    "Accept"        = "application/json"
}

$apiUrl = "$jiraBaseUrl/rest/api/2/issue/$IssueKey"

try {
    $response = Invoke-RestMethod -Uri $apiUrl -Headers $headers -Method Get
    
    $result = @{
        key         = $response.key
        summary     = $response.fields.summary
        description = $response.fields.description
    }
    
    return $result | ConvertTo-Json
}
catch {
    Write-Error "Failed to fetch JIRA issue: $_"
    exit 1
}
