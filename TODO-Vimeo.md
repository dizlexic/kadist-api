

# Task: Vimeo scrape

  - scrape https://vimeo.com/kadist
  - extract video meta data
  - use existing mechanism to actually fetch, clip and transcode videos

You'll need to set up the dev env - then take a look at `kview_videos.py`, if you make a `vimeo_videos.py` and minic `scrape_videos()`` - the output of these is a json file in config_files, maybe call this one `vimeo_videos.json` the format is:

```
[
  {
    "permalink": "http://54.218.253.163/people/abraham-cruzvillegas/",
    "title": "Abraham Cruzvillegas",
    "region": "All",
    "description": "Abraham Cruzvillegas is known for his intricate and elaborate sculptures and installations made from found and scavenged materials. He often fashions useful objects out of repurposed parts and urban detritus. Cruzvillegas is inspired by the resourcefulness he has witnessed in impoverished rural and urban areas, where people build houses and necessary objects out of recycled materials such as cars and bottles.",
    "image_url": "https://s3.amazonaws.com/arpedia/sixty_seconds.png",
    "image_width": 350,
    "image_height": 218,
    "video_url": "http://kviews.s3.amazonaws.com/AbrahamCruzvillegas.mp4"
  },
 ...
]
```

Don't worry about the upstream work, that should work unchanged. There are 3 places currently that generate these json lists in config files, Kadist's video library, Kadist video interviews, Youtube discovered relevant content. All of these just generate the above meta data lists, then the pipleline to fetch and transcode is pretty complex, not really, but it works and uses [yt_dlp](https://github.com/yt-dlp/yt-dlp) and [ffmepg](https://ffmpeg.org/) which is best left alone. If you can end up with two new additions to the repo, `vimeo_videos.py` and `config_files/vimeo_videos.json` then you're done. 
