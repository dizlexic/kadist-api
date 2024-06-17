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
RUN conda env create -f environment.yml
ENV PATH /opt/conda/envs/kadisttv/bin:$PATH

# Make port api port defined in the .env file available to the world outside this container
EXPOSE 5000

# Ingest command './ingest.sh' to run the ingestion script
RUN chmod +x ingest.sh

# Add the ingest command to the bashrc. this way you can call it with 'ingest' from docker exec
RUN alias ingest=/api/ingest.sh

CMD ["python", "app.py"]
