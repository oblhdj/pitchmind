# Frontend image. Build from the REPO ROOT (it needs contracts/ts and data/mock):
#   docker build -f apps/web/Dockerfile --build-arg NEXT_PUBLIC_LIVE_WS_URL=wss://<gateway>/ws .
FROM node:22-alpine AS build
WORKDIR /repo
COPY contracts/ts ./contracts/ts
# /api/mock-stream is force-static: next build reads the demo match from here
COPY data/mock ./data/mock
COPY apps/web/package.json apps/web/package-lock.json ./apps/web/
WORKDIR /repo/apps/web
RUN npm ci --no-audit --no-fund
COPY apps/web ./

# NEXT_PUBLIC_* values are baked into the browser bundle at build time.
ARG NEXT_PUBLIC_LIVE_WS_URL=ws://localhost:8765/ws
ARG NEXT_PUBLIC_FEED_MODE=live
ENV NEXT_PUBLIC_LIVE_WS_URL=$NEXT_PUBLIC_LIVE_WS_URL \
    NEXT_PUBLIC_FEED_MODE=$NEXT_PUBLIC_FEED_MODE \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
RUN npm run build
RUN mkdir -p .next/standalone/.next \
    && cp -r .next/static .next/standalone/.next/ \
    && if [ -d public ]; then cp -r public .next/standalone/; fi

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1 \
    MOCK_STREAM_PATH=/app/data/mock/stream.jsonl
COPY --from=build /repo/apps/web/.next/standalone ./
COPY data/mock ./data/mock
USER node
EXPOSE 3000
CMD ["node", "server.js"]
