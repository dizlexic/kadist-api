# kadist-tv
Kadist TV


# Development
```console
$ conda create -n kadisttv python=3.8
$ conda activate kadisttv
$ pip install -r requirements.txt
$ pip install -r dev-requirements.txt

```

## Development Hygiene

### precommit installation
```console
$ pre-commit install
$ pre-commit autoupdate
# black .
```

### remove unsed imports:

```console
$ autoflake --in-place --remove-all-unused-imports *.py
```

### Lint code

```console
$ flake8
```

# Set Keys for S3 to Heroku

```console
$ heroku config:set AWS_ACCESS_KEY_ID="AKIAI2ML5PDUHCAMWLDA"
$ heroku config:set AWS_SECRET_ACCESS_KEY="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"
```

# Set Heroku remote:

```console

heroku git:remote -a pacific-citadel-40116
```

## App URL

  https://pacific-citadel-40116.herokuapp.com/

## Admin URL:

  https://pacific-citadel-40116.herokuapp.com/admin


### Clip overrides

Use the `config_files/config_files/clip_overrides.json` dict, key is video_id, value should be a dict with `clip_offset` and/or `clip_length`, for example:

```python
{
  "0a7db4d3eb3e9ea536603d51a4a4b255": {
    "clip_offset": 12,
    "clip_length": 42
  }
}
```


# Import pipeline

### First generate external video list

```console
$ python external_videos.py
```

### Next generate Kadist video list

```console
$ python kadist_videos.py
```

### Fetch all videos

```console
$ python download_videos.py
```

### generate the video clips on S3

```console
$ python generate_clips.py
```

# Deployment
heroku login
./deploy.sh

# Endpoints:

## API

https://pacific-citadel-40116.herokuapp.com/
