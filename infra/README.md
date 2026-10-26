# Deploying PitchMind to Azure

```
simulator ─┐            Azure Event Hubs (Standard, Entra ID only)            ┌─ gateway (WebSocket, public)
stats ─────┤   match-events · match-stats · match-moments · match-insights ·   ├─ render
moments ───┤                    match-overlays                                ├─ agents (Agent Framework)
           └──── one Container App per stage, one image, Managed Identity ────┘
web (Next.js, public, scales to zero) ── wss ──> gateway
```

| Resource | Tier | Why |
|---|---|---|
| Container Apps environment | Consumption | 7 apps: 5 stages + gateway + web |
| Event Hubs namespace | Standard, 1 TU | one hub per topic, one consumer group per stage (Basic only has `$Default`) |
| Container Registry | Basic | one pipeline image + one web image |
| Log Analytics + Application Insights | pay-per-GB | container logs, agent traces |
| User-assigned Managed Identity | — | AcrPull + Event Hubs Data Sender/Receiver, plus Azure AI User on the Foundry resource with `-Llm foundry`; **no keys or SAS anywhere** (`disableLocalAuth: true`) |

## Prerequisites

1. Azure CLI: `winget install -e --id Microsoft.AzureCLI`, reopen the terminal, `az login`
2. Docker Desktop (only if ACR Tasks are blocked on your subscription; the script falls back to it automatically)
3. Region: Azure for Students allows only `polandcentral`, `italynorth`, `austriaeast`, `belgiumcentral`, `denmarkeast`

## Deploy

```powershell
./infra/deploy.ps1                       # offline agents (mock model): works with zero model quota
./infra/deploy.ps1 -LocalDocker          # build images locally instead of with ACR Tasks
./infra/deploy.ps1 -Llm foundry -FoundryEndpoint <project endpoint> -FoundryStrong <deployment> -FoundryFast <deployment>
```

The script runs three passes (shared resources → pipeline stages → frontend built with the gateway URL)
and prints the public URLs. The simulator loops the demo match forever (`matchSpeed`, default 4×, so the agents keep up within the model quota), so
anyone opening the URL sees a live game.

## Cost (approximate, while running)

| Item | Per day |
|---|---|
| Event Hubs Standard, 1 throughput unit | ~$0.75 |
| 6 always-on Container Apps (0.25 vCPU / 0.5 GiB) | ~$2–3 (part covered by the monthly free grant) |
| Web app | scales to zero when idle |
| Registry Basic | ~$0.17 |
| Logs | a few cents at demo volume |

**Tear down when you are done:** `az group delete -n rg-pitchmind-app --yes`

## Notes

- Background stages run exactly one replica: they hold live match state, and Event Hubs consumers
  start at the latest position, so a restarted stage resumes with the live feed.
- The gateway is a single replica because it keeps the catch-up history for late joiners.
- Foundry stays in its own resource group (`pitchmind-foundry-pl`); with `-Llm foundry`, grant the app
  identity the **Azure AI User** role on the Foundry resource (the script prints the command).
