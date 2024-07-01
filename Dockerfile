FROM continuumio/miniconda3
LABEL authors="dan"


#$ conda create -n kadisttv python=3.8
#$ conda activate kadisttv
#$ pip install -r requirements.txt
#install ffpeg and ffprobe
RUN apt-get update && apt-get install -y ffmpeg

# Set the working directory
COPY . /api
WORKDIR /api

# Create the environment:
RUN conda env create --file /api/environment.yml -n ktv-api

SHELL ["/usr/bin/env", "bash", "-c", "-l"]
ENV PATH /opt/conda/envs/ktv-api/bin:$PATH

# Make port api port defined in the .env file available to the world outside this container
#RUN pip install -r requirements.txt
#RUN pip install -r dev-requirements.txt

# Make port api port defined in the .env file available to the world outside this container
EXPOSE 5000

# Ingest command './ingest.sh' to run the ingestion script
RUN chmod +x ./bin/ingest.sh
RUN chmod +x ./bin/server.sh

# Add the ingest command to the bashrc. this way you can call it with 'ingest' from docker exec
#CMD ["tail", "-f", "/dev/null"]
CMD ["./bin/server.sh"]


