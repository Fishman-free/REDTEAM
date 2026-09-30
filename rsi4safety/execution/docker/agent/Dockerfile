FROM node:22-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 python3-pip git ca-certificates curl procps \
    && rm -rf /var/lib/apt/lists/*

# Pinned Claude Code; auto-updates must never drift a running campaign.
RUN npm install -g @anthropic-ai/claude-code@2.1.239

# Defender runs the SUT test suite inside this container.
RUN pip3 install --break-system-packages --no-cache-dir pytest fastapi uvicorn httpx

RUN useradd -m -u 1001 agent \
    && mkdir -p /agent/.claude-home /agent/workspace /agent/source \
    && chown -R agent:agent /agent

USER agent
WORKDIR /agent/workspace
ENV DISABLE_AUTOUPDATER=1 \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1 \
    PYTHONUNBUFFERED=1
CMD ["sleep", "infinity"]
