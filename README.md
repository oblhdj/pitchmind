# PitchMind (working name)

Multi-agent football insights engine on Azure, built for the Microsoft × Premier League **Inside the Game** Developer Hackathon.

PitchMind ingests synthetic football events in real time, turns them into statistics, detects the moments that matter, explains **why** they matter with cited evidence, and delivers personalized, multi-language overlays and a second-screen experience for fans, analysts and studios.

> All match data in this project is **synthetic**. No real Premier League data is used. Clubs and players are fictional.

## Pipeline

1. **Ingest** – synthetic match simulator (and CV module) stream events to Azure Event Hubs
2. **Interpret** – stats engine: pass quality, speeds, xG, pressure, momentum, control vs chaos
3. **Explain** – moment detector + agents explain why a moment matters, citing event IDs
4. **Render** – timed overlay JSON pushed through Azure Web PubSub
5. **Personalize** – persona, language, favourite club and player-focus modes

## Microsoft technologies

Microsoft Foundry · Microsoft Agent Framework · Azure Event Hubs · Azure Container Apps · Azure Functions · Azure Web PubSub · Azure Cosmos DB · Azure AI Search · Azure Static Web Apps · Application Insights · Key Vault

## Development setup (Windows)

Requires Python 3.12 and Node 20+.

```powershell
py -3.12 -m venv .venv            # or any Python 3.12 interpreter
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest                       # run tests
.\.venv\Scripts\python.exe -m ruff check .                 # lint
.\.venv\Scripts\python.exe -m pitchmind_contracts.generate # regenerate schemas + TS types
.\.venv\Scripts\python.exe tools\mock_stream.py            # regenerate mock demo match
```

See [contracts/README.md](contracts/README.md) for the message formats and the mock stream.

## Docs

- [Implementation plan](docs/PLAN.pdf) ([LaTeX source](docs/PLAN.tex))
- [Resources](docs/RESOURCES.md)
- [Team split](docs/TEAM.md)

## Status

🚧 In development — hackathon build, October 2026.

## License

[MIT](LICENSE)
