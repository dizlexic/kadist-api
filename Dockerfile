# Use the official Miniconda base image
FROM continuumio/miniconda3

# Add metadata
LABEL authors="dan"

# Install dependencies (minimal) and harden apt usage
ENV DEBIAN_FRONTEND=noninteractive
RUN set -eux; \
    apt-get update; \
    apt-get install --no-install-recommends -y \
        ca-certificates \
        ffmpeg \
        cron \
    ; \
    rm -rf /var/lib/apt/lists/*

# Define common variables
ENV WORK_DIR="/api" \
    ENV_FILE="/api/environment.yml" \
    ENV_NAME="ktv-api" \
    PATH="/opt/conda/envs/ktv-api/bin:$PATH" \
    API_PORT=1337 \
    PIP_NO_CACHE_DIR=1

# Create a non-root user
ARG USER=app
ARG UID=10001
ARG GID=10001
RUN set -eux; \
    groupadd -g "$GID" "$USER"; \
    useradd -m -u "$UID" -g "$GID" -s /bin/bash "$USER"; \
    mkdir -p "$WORK_DIR"; \
    chown -R "$USER":"$USER" "$WORK_DIR"

# Set the working directory
WORKDIR $WORK_DIR

# Copy application files (owned by non-root user)
COPY --chown=${USER}:${USER} . $WORK_DIR

# Create the Conda environment
RUN conda env create --file $ENV_FILE -n $ENV_NAME && \
    conda clean --all -y

# Set the shell
SHELL ["/usr/bin/env", "bash", "-c", "-l"]

# Expose default API port
EXPOSE $API_PORT

# Create cron file for ingest running every 4 hours (runs as non-root user)
RUN echo "0 */4 * * * ${USER} /bin/bash /api/bin/ingest.sh" > /etc/cron.d/ingest && \
    chmod 0644 /etc/cron.d/ingest
RUN crontab /etc/cron.d/ingest
# Ensure cron runs as the container starts

COPY bin/server.sh /api/bin/server.sh
RUN chmod +x /api/bin/server.sh && chown ${USER}:${USER} /api/bin/server.sh

# Drop privileges by default
USER ${USER}:${USER}

CMD ["/api/bin/server.sh"]
