import os
import tempfile
import shutil
from typing import Optional
from pathlib import Path
import logging
import urllib.parse
import requests
from flask import Flask, request, jsonify, send_file, render_template
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, USLT, APIC, TCON, TRCK, TCOM, COMM, TDRC
from mutagen.easyid3 import EasyID3
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import re
from bs4 import BeautifulSoup
from urllib.parse import quote_plus
from io import BytesIO
from googlesearch import search as google_search

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# Spotify setup
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")
))

def search_pagalworld(query):
    """Search pagalworld.com.co for a song and return the audio URL"""
    logger.info(f"Searching pagalworld for: {query}")
    
    # Use googlesearch library to search for songs on pagalworld
    search_query = f"{query} site:pagalworld.com.co mp3-songs.html"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        # Get search results from googlesearch
        search_results = list(google_search(search_query, num=5, stop=5, pause=2))
        logger.info(search_results)
        if not search_results:
            return None, None, None
        
        # Get the first result URL
        page_url = search_results[0]
        logger.info(page_url)
        # Visit the pagalworld page
        response = requests.get(page_url, headers=headers)
        response.raise_for_status()
        
        # Parse the page to find the audio download link
        page_soup = BeautifulSoup(response.text, 'html.parser')
        
        # Extract song information
        song_title = page_soup.find('title').text if page_soup.find('title') else "Unknown Song"
        logger.info(song_title)
        # Look for audio source - multiple methods to find the correct audio URL
        audio_url = None
        
        # Method 1: Look for audio tags
        audio_tags = page_soup.find_all('audio')
        for audio_tag in audio_tags:
            if audio_tag.has_attr('src'):
                audio_url = audio_tag['src']
                break
        
        # Method 2: Look for download links
        if not audio_url:
            download_links = page_soup.find_all('a', href=True)
            for link in download_links:
                href = link['href']
                if href.endswith('.mp3'):
                    audio_url = href
                    break
        
        # Method 3: Look for source tags
        if not audio_url:
            source_tags = page_soup.find_all('source')
            for source in source_tags:
                if source.has_attr('src'):
                    audio_url = source['src']
                    break
        
        # Method 4: Look for .dbutton elements
        if not audio_url:
            download_buttons = page_soup.select('.dbutton a')
            for button in download_buttons:
                if button.has_attr('href'):
                    audio_url = button['href']
                    break
        
        if not audio_url:
            return None, page_url, None
        
        # If audio URL is relative, convert to absolute URL
        if audio_url and not audio_url.startswith(('http://', 'https://')):
            base_url = urllib.parse.urlparse(page_url)
            base_domain = f"{base_url.scheme}://{base_url.netloc}"
            
            # Handle different relative URL formats
            if audio_url.startswith('/'):
                audio_url = f"{base_domain}{audio_url}"
            else:
                # Relative to current path
                path_parts = base_url.path.split('/')
                # Remove the filename
                if '.' in path_parts[-1]:
                    path_parts = path_parts[:-1]
                base_path = '/'.join(path_parts)
                audio_url = f"{base_domain}{base_path}/{audio_url}"
        
        # Try to extract title
        title_elem = page_soup.find('title') or page_soup.select_one('h1') or page_soup.select_one('.songname')
        title = title_elem.text.strip() if title_elem else query
        
        return audio_url, page_url, title
        
    except Exception as e:
        logger.error(f"Error searching pagalworld: {str(e)}")
        return None, None, None

def download_mp3(url, filename):
    """Download MP3 file from URL"""
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Referer': 'https://pagalworld.com.co/'
        }
        response = requests.get(url, headers=headers, stream=True)
        response.raise_for_status()
        
        with open(filename, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
        
        return True
    except Exception as e:
        logger.error(f"Error downloading MP3: {str(e)}")
        return False

def get_complete_spotify_metadata(track_id):
    """Get detailed metadata from Spotify for a track"""
    try:
        # Get track details
        track = sp.track(track_id)
        
        # Get audio features (tempo, key, etc.)
        audio_features = sp.audio_features(track_id)[0]
    
        
        
        # Combine all metadata
        metadata = {
            "title": track['name'],
            "artist": track['artists'][0]['name'],
            "album": track['album']['name'],
            "year": track['album']['release_date'][:4],
            "cover_url": track['album']['images'][0]['url'] if track['album']['images'] else None,
            "track_number": track.get('track_number', 1),
            "disc_number": track.get('disc_number', 1),
            "total_tracks": album.get('total_tracks', 1),
            "genres": artist.get('genres', []),
            "duration_ms": track.get('duration_ms', 0),
            "release_date": track['album']['release_date'],
            "explicit": track.get('explicit', False),
            "popularity": track.get('popularity', 0),
            "tempo": audio_features.get('tempo') if audio_features else None,
            "key": audio_features.get('key') if audio_features else None,
            "artists": [artist['name'] for artist in track['artists']],
            "composers": [],  # No direct composer info in Spotify API
            "album_artist": track['album'].get('album_artist', track['artists'][0]['name']),
        }
        
        return metadata
        
    except Exception as e:
        logger.error(f"Error fetching Spotify metadata: {str(e)}")
        return None

def embed_metadata(file_path, metadata, lyrics=""):
    """Embed metadata and lyrics into the MP3 file."""
    logger.info(f"Embedding metadata into: {file_path}")
    
    try:
        audio = MP3(file_path, ID3=ID3)
        try:
            audio.add_tags()
        except:
            pass

        # Add basic metadata
        audio.tags.add(TIT2(encoding=3, text=metadata["title"]))
        audio.tags.add(TPE1(encoding=3, text=metadata["artist"]))
        audio.tags.add(TALB(encoding=3, text=metadata["album"]))
        
        if "year" in metadata and metadata["year"]:
            audio.tags.add(TYER(encoding=3, text=metadata["year"]))
            audio.tags.add(TDRC(encoding=3, text=metadata["year"]))
        
        # Add track number if available
        if "track_number" in metadata:
            track_text = f"{metadata['track_number']}"
            if "total_tracks" in metadata:
                track_text += f"/{metadata['total_tracks']}"
            audio.tags.add(TRCK(encoding=3, text=track_text))
        
        # Add genre if available
        if "genres" in metadata and metadata["genres"]:
            audio.tags.add(TCON(encoding=3, text=metadata["genres"][0]))
        
        # Add composers if available
        if "composers" in metadata and metadata["composers"]:
            audio.tags.add(TCOM(encoding=3, text=metadata["composers"]))
        
        # Add comments
        if "popularity" in metadata:
            audio.tags.add(COMM(encoding=3, lang='eng', desc='Popularity', 
                              text=f"Popularity: {metadata['popularity']}/100"))
        
        # Add lyrics if available
        if lyrics:
            audio.tags.add(USLT(encoding=3, desc="Lyrics", text=lyrics))

        # Add cover art if available
        if "cover_url" in metadata and metadata["cover_url"]:
            try:
                response = requests.get(metadata["cover_url"])
                if response.status_code == 200:
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=response.content
                    ))
            except Exception as e:
                logger.warning(f"Could not add cover art: {str(e)}")

        audio.save()
        return True
    except Exception as e:
        logger.error(f"Failed to embed metadata: {str(e)}")
        return False


def embed_metadata_memory(mp3_data: bytes, metadata: dict, lyrics: str = "") -> bytes | None:
    """Embed metadata and lyrics into the MP3 file in memory and return the updated data."""
    logger.info("Embedding metadata into in-memory MP3 data")
    
    try:
        mp3_io = BytesIO(mp3_data)
        audio = MP3(mp3_io, ID3=ID3)

        try:
            audio.add_tags()
        except Exception:
            pass

        # Add basic metadata
        audio.tags.add(TIT2(encoding=3, text=metadata["title"]))
        audio.tags.add(TPE1(encoding=3, text=metadata["artist"]))
        audio.tags.add(TALB(encoding=3, text=metadata["album"]))
        
        if "year" in metadata and metadata["year"]:
            audio.tags.add(TYER(encoding=3, text=metadata["year"]))
            audio.tags.add(TDRC(encoding=3, text=metadata["year"]))
        
        if "track_number" in metadata:
            track_text = f"{metadata['track_number']}"
            if "total_tracks" in metadata:
                track_text += f"/{metadata['total_tracks']}"
            audio.tags.add(TRCK(encoding=3, text=track_text))
        
        if "genres" in metadata and metadata["genres"]:
            audio.tags.add(TCON(encoding=3, text=metadata["genres"][0]))
        
        if "composers" in metadata and metadata["composers"]:
            audio.tags.add(TCOM(encoding=3, text=metadata["composers"]))
        
        if "popularity" in metadata:
            audio.tags.add(COMM(encoding=3, lang='eng', desc='Popularity',
                                text=f"Popularity: {metadata['popularity']}/100"))

        if lyrics:
            audio.tags.add(USLT(encoding=3, desc="Lyrics", text=lyrics))

        if "cover_url" in metadata and metadata["cover_url"]:
            try:
                response = requests.get(metadata["cover_url"])
                if response.status_code == 200:
                    audio.tags.add(APIC(
                        encoding=3,
                        mime='image/jpeg',
                        type=3,
                        desc='Cover',
                        data=response.content
                    ))
            except Exception as e:
                logger.warning(f"Could not add cover art: {str(e)}")

        # Save tags to a new BytesIO object
        output_io = BytesIO()
        audio.save(output_io)
        return output_io.getvalue()

    except Exception as e:
        logger.error(f"Failed to embed metadata: {str(e)}")
        return None

@app.route('/search', methods=['POST'])
def search():
    """Search for a song on pagalworld.com.co and return the audio URL"""
    # input:{query: "tum he ho"}
    # output:{success: True, audio_url: "url", page_url: "url", title: "title"}
    # sample input: {"query": "tum he ho"}
    # sample output: {"success": True, "audio_url": "url", "page_url": "url", "title": "title"}
    try:
        logger.info("search")
        # Get the query from the request
        data = request.json
        if not data or "query" not in data:
            return jsonify({"success": False, "error": "Missing 'query' parameter"}), 400
        
        query = data["query"]
        audio_url, page_url, title = search_pagalworld(query)
        
        if not audio_url:
            return jsonify({
                "success": False, 
                "error": "Could not find audio URL for the given query"
            }), 404
        
        return jsonify({
            "success": True,
            "audio_url": audio_url,
            "page_url": page_url,
            "title": title
        })
    
    except Exception as e:
        logger.error(f"Search endpoint error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/download', methods=['POST'])
def download():
    """Download song from pagalworld.com.co and embed Spotify metadata"""
    temp_dir = None
    try:
        # Get the track data from the request
        data = request.json
        if not data:
            return jsonify({"success": False, "error": "Missing request data"}), 400
        
        track = data.get("track", {})
        track_name = track.get("name", "")
        artist_name = track.get("artists", [{}])[0].get("name", "")
        
        # Build metadata directly from the request data
        metadata = {
            "title": track_name,
            "artist": artist_name,
            "album": track.get("album_name", track.get("name", "")),  # Fallback to track name if album name is missing
            "year": track.get("release_date", "")[:4] if track.get("release_date") else "",
            "cover_url": None,
            "track_number": track.get("track_number", 1),
            "total_tracks": track.get("total_tracks", 1),
            "genres": [],
            "duration_ms": track.get("duration_ms", 0),
            "release_date": track.get("release_date", ""),
            "explicit": track.get("explicit", False),
            "popularity": track.get("popularity", 0),
            "artists": [artist.get("name", "") for artist in track.get("artists", [])],
            "album_artist": artist_name,
        }
        
        # Handle album data specifically since it can have different structures
        if "album" in track:
            album = track["album"]
            metadata["album"] = album.get("name", "")
            metadata["year"] = album.get("release_date", "")[:4] if album.get("release_date") else ""
            metadata["release_date"] = album.get("release_date", "")
            metadata["total_tracks"] = album.get("total_tracks", 1)
            
            # Get cover URL if available
        if "images" in track and len(track["images"]) > 0:
                metadata["cover_url"] = track["images"][0].get("url")
        
        # logger.info(f"track: {track}")
        # logger.info(f"metadata: {metadata}")
        lyrics = data.get("lyrics", "")
        
        # Construct search query
        query = f"{track_name.split(' (')[0]} by {artist_name}"
        
        # Search for the song
        audio_url, page_url, title = search_pagalworld(query)
        if not audio_url:
            audio_url, page_url, title = search_pagalworld(f"{track_name.split(' (')[0]}")
        logger.info(f"audio_url: {audio_url}\n page_url: {page_url} \n title: {title}")
        if not audio_url:
            return jsonify({
                "success": False, 
                "error": "Could not find song on pagalworld.com.co"
            }), 404
        
        # Method 1: Download to disk first
        if False:  # Set to True if you want to use disk-based processing
            # Create temporary directory
            temp_dir = Path(tempfile.mkdtemp())
            mp3_file = temp_dir / f"{secure_filename(track_name)}.mp3"
            
            # Download the MP3
            if not download_mp3(audio_url, mp3_file):
                return jsonify({
                    "success": False,
                    "error": "Failed to download MP3"
                }), 500
            
            # Embed metadata
            if not embed_metadata(mp3_file, metadata, lyrics):
                return jsonify({
                    "success": False,
                    "error": "Failed to embed metadata"
                }), 500
            
            # Send the file
            return send_file(
                mp3_file, 
                mimetype="audio/mpeg",
                as_attachment=True,
                download_name=f"{track_name} - {artist_name}.mp3"
            )
        
        # Method 2: Process in memory (more efficient)
        else:
            # Download the MP3 directly to memory
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Referer': 'https://pagalworld.com.co/'
            }
            
            response = requests.get(audio_url, headers=headers)
            response.raise_for_status()
            
            # Embed metadata
            modified_mp3 = embed_metadata_memory(response.content, metadata, lyrics)
            
            if not modified_mp3:
                return jsonify({
                    "success": False,
                    "error": "Failed to embed metadata"
                }), 500
            
            # Send the file
            return send_file(
                BytesIO(modified_mp3),
                mimetype="audio/mpeg",
                as_attachment=True,
                download_name=f"{track_name} - {artist_name}.mp3"
                )

    except Exception as e:
        logger.error(f"Download endpoint error: {str(e)}")
        return jsonify({"success": False, "error": str(e)}), 500
    
    finally:
        # Clean up the temporary directory if it was created
        if temp_dir:
            logger.info(f"Cleaning up temporary directory: {temp_dir}")
            shutil.rmtree(temp_dir, ignore_errors=True)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 1111))
    # app.run(host="0.0.0.0", port=port, debug=True)
    app.run(port=port, debug=True)
    