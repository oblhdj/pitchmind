<#
.SYNOPSIS
  Live demo switches for the deployed agents: failure recovery and the Verifier.

.EXAMPLE
  ./infra/demo.ps1 kill                    # Narrative agent down: goals, saves, cards air the template ("auto")
  ./infra/demo.ps1 kill -Agent explain     # same for explanations (pressure, big chances, momentum)
  ./infra/demo.ps1 plant                   # each writer's first draft gets a wrong xG; the Verifier rejects it
  ./infra/demo.ps1 restore                 # back to normal
  ./infra/demo.ps1 status

.NOTES
  Each switch updates the agents app's settings, then stops and starts it (about a minute) and
  waits for the new replica: on this Container Apps environment an env-only update leaves the
  running replica on the old settings, and revision restart is not available.
  The studio shows the effect per insight (agent trace, "auto" badge); the agents log
  "demo: planted xG ..." and "draft rejected: ...". Running ./infra/deploy.ps1 also restores normal settings.
#>
param(
    [Parameter(Mandatory)][ValidateSet("kill", "plant", "restore", "status")][string]$Action,
    [ValidateSet("narrative", "explain", "recap", "persona", "language")][string]$Agent = "narrative",
    [string]$ResourceGroup = "rg-pitchmind-app",
    [string]$App = "pitchmind-agents"
)
$ErrorActionPreference = "Stop"

function Invoke-Az {
    $out = & az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args -join ' ') failed" }
    return $out
}

$switches = @("PITCHMIND_DISABLED_AGENTS", "PITCHMIND_DEMO_PLANT")
if ($Action -ne "status") {
    switch ($Action) {
        "kill" { Invoke-Az containerapp update -g $ResourceGroup -n $App --set-env-vars "PITCHMIND_DISABLED_AGENTS=$Agent" -o none }
        "plant" { Invoke-Az containerapp update -g $ResourceGroup -n $App --set-env-vars "PITCHMIND_DEMO_PLANT=1" -o none }
        "restore" { Invoke-Az containerapp update -g $ResourceGroup -n $App --remove-env-vars @switches -o none }
    }
    $id = Invoke-Az containerapp show -g $ResourceGroup -n $App --query id -o tsv
    $since = (Get-Date).ToUniversalTime()
    Write-Host "restarting $App so it picks up the settings..."
    Invoke-Az rest --method post --url "https://management.azure.com$id/stop?api-version=2024-03-01" -o none
    Invoke-Az rest --method post --url "https://management.azure.com$id/start?api-version=2024-03-01" -o none
    $ready = $false
    for ($i = 0; $i -lt 36 -and -not $ready; $i++) {
        $replica = Invoke-Az containerapp replica list -g $ResourceGroup -n $App --query "[0].{created:properties.createdTime,state:properties.runningState}" -o json | Out-String | ConvertFrom-Json
        $ready = $replica -and ([datetime]$replica.created).ToUniversalTime() -gt $since -and $replica.state -eq "Running"
        if (-not $ready) { Start-Sleep -Seconds 5 }
    }
    if (-not $ready) { throw "$App did not come back within 3 minutes; check the portal" }
    Write-Host "$App is running again with the new settings"
}

$settings = Invoke-Az containerapp show -g $ResourceGroup -n $App --query "properties.template.containers[0].env" -o json | Out-String | ConvertFrom-Json
$active = $settings | Where-Object { $switches -contains $_.name }
if ($active) {
    $active | ForEach-Object { Write-Host "$($_.name)=$($_.value)" }
} else {
    Write-Host "no demo switch on: all agents normal"
}
