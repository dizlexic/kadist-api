# Use the official Miniconda base image
FROM continuumio/miniconda3

# Add metadata
LABEL authors="dan"

# Install dependencies
RUN apt-get update && apt-get install -y ffmpeg cron && \
   apt-get clean && rm -rf /var/lib/apt/lists/*

# Define common variables
ENV WORK_DIR="/api" \
   ENV_FILE="/api/environment.yml" \
   ENV_NAME="ktv-api" \
   PATH="/opt/conda/envs/ktv-api/bin:$PATH" \
   API_PORT="1337"

# Set the working directory
WORKDIR $WORK_DIR

# Copy application files
COPY . $WORK_DIR

# Create the Conda environment
RUN conda env create --file $ENV_FILE -n $ENV_NAME && \
   conda clean --all -y

# Set the shell
SHELL ["/usr/bin/env", "bash", "-c", "-l"]

# Expose default API port
EXPOSE $API_PORT

# Create cron file for ingest running every 4 hours
RUN echo "0 */4 * * * root /bin/bash /api/bin/ingest.sh" > /etc/cron.d/ingest && \
    chmod 0644 /etc/cron.d/ingest
RUN crontab /etc/cron.d/ingest
# Ensure cron runs as the container starts

COPY bin/server.sh /api/bin/server.sh
RUN chmod +x /api/bin/server.sh

CMD ["/api/bin/server.sh"]
