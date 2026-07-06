"""
fetch_images.py — Auto-fetch vehicle images from Wikipedia

This script fetches images for vehicles in data.json that don't yet have entries
in photos.json. It searches Wikipedia for the make/model and extracts image URLs.

Usage:
  python scripts/fetch_images.py [--data DATA_FILE] [--photos PHOTOS_FILE] [--limit N]

Example:
  python scripts/fetch_images.py --limit 10  # Fetch images for first 10 missing vehicles

Requirements:
  pip install requests beautifulsoup4
"""

import json
import os
import sys
import argparse
from pathlib import Path
from typing import Optional, Dict, Any
from urllib.parse import quote

try:
    import requests
except ImportError:
    print("ERROR: requests library not installed. Run: pip install requests beautifulsoup4")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 library not installed. Run: pip install beautifulsoup4")
    sys.exit(1)


def search_wikipedia_image(make: str, model: str) -> Optional[Dict[str, Any]]:
    """
    Search Wikipedia for a vehicle image.
    Returns dict with 'url' and 'source' keys, or None if not found.
    """
    try:
        query = f"{make} {model}".strip()

        # Try Wikipedia API first for article images
        headers = {'User-Agent': 'JDM-Eligibility-Fetcher/1.0 (+https://caniimportit.com.au)'}
        wiki_url = "https://en.wikipedia.org/w/api.php"
        params = {
            'action': 'query',
            'titles': query,
            'prop': 'pageimages|pageterms',
            'piprop': 'original',
            'format': 'json',
            'formatversion': 2,
        }

        response = requests.get(wiki_url, params=params, headers=headers, timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get('query', {}).get('pages'):
            page = data['query']['pages'][0]
            if 'original' in page:
                return {
                    'url': page['original']['source'],
                    'source': 'wikipedia',
                    'make': make,
                    'model': model,
                }

        # Fallback: search and extract from page
        search_url = f"https://en.wikipedia.org/wiki/{quote(query)}"
        resp = requests.get(search_url, timeout=5)

        if resp.status_code == 200:
            soup = BeautifulSoup(resp.content, 'html.parser')
            # Find infobox image
            infobox = soup.find('table', {'class': 'infobox'})
            if infobox:
                img = infobox.find('img')
                if img and img.get('src'):
                    src = img['src']
                    if src.startswith('//'):
                        src = 'https:' + src
                    if src.startswith('http'):
                        return {
                            'url': src,
                            'source': 'wikipedia',
                            'make': make,
                            'model': model,
                        }

        return None

    except Exception as e:
        print(f"  [!] Error fetching image for {make} {model}: {e}", flush=True)
        return None


def load_json_safe(path: str) -> Dict:
    """Load JSON file, return empty dict if missing."""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: could not read {path}: {e}")
        return {}


def main():
    parser = argparse.ArgumentParser(
        description='Auto-fetch vehicle images from Wikipedia for new vehicles in data.json'
    )
    parser.add_argument('--data', default='functions/_data/data.json',
                        help='Path to data.json')
    parser.add_argument('--photos', default='functions/_data/photos.json',
                        help='Path to photos.json')
    parser.add_argument('--limit', type=int, default=50,
                        help='Max number of images to fetch (default: 50)')

    args = parser.parse_args()

    # Resolve paths relative to repo root
    repo_root = Path(__file__).parent.parent
    data_path = repo_root / args.data
    photos_path = repo_root / args.photos

    print(f"Loading data from {data_path}")
    data = load_json_safe(str(data_path))

    print(f"Loading photos from {photos_path}")
    photos = load_json_safe(str(photos_path))

    # Collect all vehicles
    vehicles = []
    for rec in data.get('mre', []) + data.get('sev', []):
        make = rec.get('Make', '').strip()
        model = rec.get('Model', '').strip()
        code = rec.get('code', '').strip()

        if make and model:
            vehicles.append({
                'make': make,
                'model': model,
                'code': code or f"{make}-{model}",
                'source_type': rec.get('type', 'UNKNOWN'),
            })

    # Find vehicles without images
    missing = []
    for v in vehicles:
        # Check if any variant has an image
        code_norm = v['code'].upper().replace(' ', '').replace('-', '')
        if code_norm not in photos:
            missing.append(v)

    if not missing:
        print("[OK] All vehicles have images!")
        return

    print(f"\nFound {len(missing)} vehicles without images. Fetching... (limit: {args.limit})")
    print()

    fetched = 0
    for v in missing[:args.limit]:
        if fetched >= args.limit:
            break

        print(f"  {v['make']:20} {v['model']:20}", end=' ', flush=True)
        img = search_wikipedia_image(v['make'], v['model'])

        if img:
            code_norm = v['code'].upper().replace(' ', '').replace('-', '')
            photos[code_norm] = img
            fetched += 1
            print("[+]")
        else:
            print("[-]")

    if fetched == 0:
        print("\nNo images were fetched. Try expanding your search or adding images manually.")
        return

    # Write photos.json
    print(f"\nSaving {fetched} new images to {photos_path}")
    photos_path.parent.mkdir(parents=True, exist_ok=True)
    with open(photos_path, 'w', encoding='utf-8') as f:
        json.dump(photos, f, indent=2, ensure_ascii=False)

    print(f"[OK] Done! Fetched {fetched} images.")
    print(f"     {len(missing) - fetched} vehicles still missing images (limit reached)")


if __name__ == '__main__':
    main()
