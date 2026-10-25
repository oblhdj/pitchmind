# One image for every Python stage. Each Azure Container App runs it with its stage name:
#   python -m pitchmind_runner.cloud simulator|stats|moments|agents|render|gateway
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY contracts ./contracts
COPY libs ./libs
COPY services ./services

RUN pip install \
        ./contracts \
        ./libs/football \
        "./libs/bus[eventhubs]" \
        ./services/simulator \
        ./services/stats-engine \
        ./services/moment-detector \
        ./services/agents \
        ./services/render \
        ./services/runner \
    && useradd --create-home --uid 10001 pitchmind

USER pitchmind
EXPOSE 8765
ENTRYPOINT ["python", "-m", "pitchmind_runner.cloud"]
CMD ["gateway"]
