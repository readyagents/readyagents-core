# Official image for ReadyAgents Core. Local-first CLI — no cluster, no extra services.
FROM python:3.12-slim-bookworm

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
COPY examples ./examples
COPY docs ./docs

RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

WORKDIR /work
ENV READYAGENTS_HOME=/work/.readyagents

ENTRYPOINT ["readyagents"]
CMD ["--help"]
