import csv
import html
import json
import os
import sys

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm


# Output JSON structure
# {
# 	"permalink": "mandatory::<absolute url>",
#   "videos": [{
#     "url": "mandatory::<absolute url>",
#     "type": "mandatory::<video/mp4>"
#   }],
# 	"images": [{
# 		"caption": "mandatory::<text>",
# 		"url": "mandatory::<absolute url>"
#       "height": "mandatory::<absolute height in pixels>",
#       "width": "mandatory::<absolute width in pixels>",
# 	}],
# 	"title": "mandatory::<title>",
# 	"creator": "mandatory::<creator name>",
# 	"creator_data": "optional::<unstructured text>",
# 	"description": "mandatory::<unstructured text>",
# 	"tags": [
# 		"optional::<unstructured text>"
# 	],	"creation_year": "optional::<year number",
# 	"collection": "mandatory::<structured text>"
# }

# CSV structure
# ID,NAME,n/a,URL,n/a
# EXAMPLE
# 218,White Corner,Film &amp; Video,https://org-kadist-kvl-media-output.s3-us-west-1.amazonaws.com/HLS/Alexandre_Arrechea/WhiteCorner2channelFINAL2/index.m3u8,,
# CSV location
# f'{os.getcwd()}/KADIST-Export.csv')

# wordpress url template
# f"https://kadist.org?page_id={ID}"
# On each row, create a JSON object with the required fields and write it to a file
# Attempt to scrape the video metadata from the provided URL template
# f"https://kadist.org?page_id={ID}"
# parse the returned HTML to determine what information should be in which field value on the output json.


def get_wordpress_url(page_id):
    """Construct WordPress URL from page ID."""
    return f"https://kadist.org?page_id={page_id}"


def scrape_wordpress_page(url):
    """Scrape WordPress page and extract metadata."""
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract title
        title_tag = soup.find('h1') or soup.find('title')
        title = title_tag.get_text(strip=True) if title_tag else ""

        # Extract creator
        creator = ""
        creator_tag = soup.find('meta', {'name': 'author'}) or soup.find(class_='author')
        if creator_tag:
            creator = creator_tag.get('content', '') if creator_tag.name == 'meta' else creator_tag.get_text(strip=True)

        # Extract description
        description = ""
        desc_tag = soup.find('meta', {'name': 'description'}) or soup.find(class_='description')
        if desc_tag:
            description = desc_tag.get('content', '') if desc_tag.name == 'meta' else desc_tag.get_text(strip=True)

        # Extract tags
        tags = []
        tag_elements = soup.find_all(class_='tag') or soup.find_all('meta', {'property': 'article:tag'})
        for tag in tag_elements:
            tag_text = tag.get('content', '') if tag.name == 'meta' else tag.get_text(strip=True)
            if tag_text:
                tags.append(tag_text)

        # Extract images
        images = []
        for img in soup.find_all('img'):
            img_url = img.get('src', '')
            if img_url and img_url.startswith('http'):
                image_data = {
                    'url': img_url,
                    'caption': img.get('alt', ''),
                    'width': img.get('width', ''),
                    'height': img.get('height', '')
                }
                images.append(image_data)

        # Extract videos
        videos = []
        for video in soup.find_all('video'):
            sources = video.find_all('source')
            for source in sources:
                video_url = source.get('src', '')
                if video_url:
                    videos.append({
                        'url': video_url,
                        'type': source.get('type', 'video/mp4')
                    })

        # Extract creation year
        creation_year = ""
        year_tag = soup.find('meta', {'property': 'article:published_time'})
        if year_tag:
            date_str = year_tag.get('content', '')
            if date_str and len(date_str) >= 4:
                creation_year = date_str[:4]

        # Extract collection
        collection = ""
        collection_tag = soup.find(class_='collection')
        if collection_tag:
            collection = collection_tag.get_text(strip=True)

        # Extract creator data
        creator_data = ""
        creator_data_tag = soup.find(class_='creator-bio') or soup.find(class_='artist-bio')
        if creator_data_tag:
            creator_data = creator_data_tag.get_text(strip=True)

        return {
            'title': title,
            'creator': creator,
            'creator_data': creator_data,
            'artist_bio': creator_data,
            'description': description,
            'tags': tags,
            'images': images,
            'videos': videos,
            'creation_year': creation_year,
            'collection': collection
        }
    except Exception as e:
        print(f"Error scraping {url}: {e}")
        return None


def create_json_object(csv_row, scraped_data, page_id):
    """Generate JSON object from CSV row and scraped data."""
    # Parse CSV row
    row_id = csv_row[0] if len(csv_row) > 0 else ""
    name = csv_row[1] if len(csv_row) > 1 else ""
    collection = csv_row[2] if len(csv_row) > 2 else ""
    video_url = csv_row[3] if len(csv_row) > 3 else ""

    # Unescape HTML entities
    name = html.unescape(name)
    collection = html.unescape(collection)

    # Build JSON object
    json_obj = {
        'permalink': get_wordpress_url(page_id),
        'title': scraped_data.get('title', name) or name,
        'creator': scraped_data.get('creator', ''),
        'creator_data': scraped_data.get('creator_data', ''),
        'artist_bio': scraped_data.get('artist_bio', ''),
        'description': scraped_data.get('description', ''),
        'tags': scraped_data.get('tags', []),
        'creation_year': scraped_data.get('creation_year', ''),
        'collection': scraped_data.get('collection', collection) or collection,
        'images': scraped_data.get('images', []),
        'videos': scraped_data.get('videos', [])
    }

    # Add CSV video URL if provided
    if video_url:
        csv_video = {
            'url': video_url,
            'type': 'application/x-mpegURL' if '.m3u8' in video_url else 'video/mp4'
        }
        if csv_video not in json_obj['videos']:
            json_obj['videos'].insert(0, csv_video)

    return json_obj


def process_csv(csv_path, output_dir):
    """Process CSV file and generate JSON files."""
    os.makedirs(output_dir, exist_ok=True)

    with open(csv_path, 'r', encoding='utf-8') as csvfile:
        reader = csv.reader(csvfile)
        header = next(reader, None)  # Skip header row

        rows = list(reader)
        limit = 2
        for row in tqdm(rows, desc="Processing CSV rows"):
            if limit <= 0:
                break
            limit -= 1
            if not row or not row[0]:
                continue

            page_id = row[0].strip()
            wordpress_url = get_wordpress_url(page_id)

            # Scrape WordPress page
            scraped_data = scrape_wordpress_page(wordpress_url)
            if not scraped_data:
                scraped_data = {
                    'title': '', 'creator': '', 'creator_data': '',
                    'description': '', 'tags': [], 'images': [],
                    'videos': [], 'creation_year': '', 'collection': ''
                }

            # Create JSON object
            json_obj = create_json_object(row, scraped_data, page_id)

            # Write to file
            output_file = os.path.join(output_dir, f"{page_id}.json")
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(json_obj, f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    csv_file = os.path.join(os.getcwd(), 'KADIST-Export.csv')
    output_directory = os.path.join(os.getcwd(), 'storage', 'imported_videos')

    if not os.path.exists(csv_file):
        print(f"Error: CSV file not found at {csv_file}")
        sys.exit(1)

    print(f"Processing CSV: {csv_file}")
    print(f"Output directory: {output_directory}")

    process_csv(csv_file, output_directory)

    print("Import complete!")
