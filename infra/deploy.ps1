<#
.SYNOPSIS
  Deploy PitchMind to Azure (Event Hubs + Container Apps) in three passes.

.EXAMPLE
  ./infra/deploy.ps1                                   # offline agents (mock model)
  ./infra/deploy.ps1 -Llm foundry -FoundryEndpoint https://pitchmind.services.ai.azure.com/api/projects/pitchmind `
                     -FoundryStrong Phi-4 -FoundryFast Phi-4-mini-instruct

.NOTES
  Needs the Azure CLI (`winget install -e --id Microsoft.AzureCLI`) and `az login`.
  Run from the repo root. Tear everything down with: az group delete -n <ResourceGroup> --yes
#>
param(
    [string]$ResourceGroup = "rg-pitchmind-app",
    [string]$Location = "polandcentral",
    [ValidateSet("mock", "foundry")][string]$Llm = "mock",
    [string]$FoundryEndpoint = "",
    [string]$FoundryStrong = "",
    [string]$FoundryFast = "",
    [string]$MatchSpeed = "6",
    [switch]$LocalDocker  # build images with local Docker instead of ACR Tasks
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)

function Invoke-Az {
    $out = & az @args
    if ($LASTEXITCODE -ne 0) { throw "az $($args -join ' ') failed" }
    return $out
}

function Deploy([hashtable]$Extra) {
    $params = @(
        "location=$Location", "llm=$Llm", "matchSpeed=$MatchSpeed",
        "foundryProjectEndpoint=$FoundryEndpoint", "foundryModelStrong=$FoundryStrong", "foundryModelFast=$FoundryFast"
    ) + ($Extra.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" })
    $json = Invoke-Az deployment group create -g $ResourceGroup -f infra/main.bicep -p @params --query properties.outputs -o json
    return ($json | Out-String | ConvertFrom-Json)
}

function Build-Image([string]$Acr, [string]$Image, [string]$Dockerfile, [string[]]$BuildArgs) {
    $server = "$Acr.azurecr.io"
    if (-not $LocalDocker) {
        $acrArgs = @("acr", "build", "-r", $Acr, "-t", $Image, "-f", $Dockerfile)
        foreach ($b in $BuildArgs) { $acrArgs += @("--build-arg", $b) }
        & az @acrArgs . | Out-Host
        if ($LASTEXITCODE -eq 0) { return "$server/$Image" }
        Write-Warning "ACR Tasks build failed (often blocked on student subscriptions); falling back to local Docker."
    }
    Invoke-Az acr login -n $Acr | Out-Host
    $dockerArgs = @("build", "-t", "$server/$Image", "-f", $Dockerfile)
    foreach ($b in $BuildArgs) { $dockerArgs += @("--build-arg", $b) }
    & docker @dockerArgs . | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "docker build failed for $Image" }
    & docker push "$server/$Image" | Out-Host
    if ($LASTEXITCODE -ne 0) { throw "docker push failed for $Image" }
    return "$server/$Image"
}

Write-Host "== checking Azure login"
Invoke-Az account show --query "{subscription:name, user:user.name}" -o table | Out-Host

Write-Host "== registering resource providers (first time only, can take a few minutes)"
foreach ($ns in "Microsoft.App", "Microsoft.EventHub", "Microsoft.ContainerRegistry", "Microsoft.OperationalInsights", "Microsoft.Insights") {
    Invoke-Az provider register --namespace $ns --wait | Out-Null
}

Write-Host "== resource group $ResourceGroup ($Location)"
Invoke-Az group create -n $ResourceGroup -l $Location -o none

Write-Host "== pass 1/3: registry, Event Hubs, identity, logs"
$out = Deploy @{}
$acr = $out.acrName.value
$tag = (git rev-parse --short HEAD) + "-" + (Get-Date -Format "MMddHHmm")

Write-Host "== building the pipeline image"
$pythonImage = Build-Image $acr "pitchmind-pipeline:$tag" "Dockerfile" @()

Write-Host "== pass 2/3: the six pipeline stages"
$out = Deploy @{ pythonImage = $pythonImage }
$gatewayUrl = "wss://$($out.gatewayFqdn.value)/ws"

Write-Host "== building the frontend for $gatewayUrl"
$webImage = Build-Image $acr "pitchmind-web:$tag" "apps/web/Dockerfile" @("NEXT_PUBLIC_LIVE_WS_URL=$gatewayUrl", "NEXT_PUBLIC_FEED_MODE=live")

Write-Host "== pass 3/3: the frontend"
$out = Deploy @{ pythonImage = $pythonImage; webImage = $webImage }

if ($Llm -eq "foundry") {
    Write-Host ""
    Write-Host "Grant the app identity access to Foundry (once):"
    Write-Host "  az role assignment create --role 'Azure AI User' --assignee-object-id $($out.identityPrincipalId.value) --assignee-principal-type ServicePrincipal --scope <Foundry resource id>"
}

Write-Host ""
$webUrl = "https://$($out.webFqdn.value)"
Write-Host "PitchMind is live:"
Write-Host "  Second screen : $webUrl"
Write-Host "  Overlay       : $webUrl/overlay"
Write-Host "  Studio        : $webUrl/studio"
Write-Host "  WebSocket     : $gatewayUrl"
