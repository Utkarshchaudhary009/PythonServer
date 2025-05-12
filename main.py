import os
import tempfile
import shutil
from typing import Optional
from pathlib import Path
import logging
from pydantic import BaseModel
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TYER, USLT, APIC
import cloudinary
import cloudinary.uploader
from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials
from youtubesearchpython import VideosSearch
import yt_dlp
from uuid import uuid4
import subprocess
subprocess.run(["ffmpeg",'-version'])

# install uuid wth code = pip install uuid
# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="Music Processing API")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Configure Cloudinary
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# Spotify setup
sp = Spotify(auth_manager=SpotifyClientCredentials(
    client_id=os.getenv("SPOTIFY_CLIENT_ID"),
    client_secret=os.getenv("SPOTIFY_CLIENT_SECRET")
))

# Pydantic models
class ProcessRequest(BaseModel):
    query: str
    lyrics: Optional[str] = ""

class ProcessResponse(BaseModel):
    public_id: str
    cloudinary_url: str
    youtube_url: str

async def search_youtube_ytdlp(query: str) -> tuple[str, str]:
    """Search YouTube for a video and return its URL and title."""
    logger.info(f"Searching YouTube for: {query}")
    ydl_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warning': True,
        'skip_download': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        result = ydl.extract_info(f"ytsearch:{query}", download=False)
        if not result or not result.get('entries'):
            raise HTTPException(status_code=404, detail="No YouTube video found")
        
        video = result['entries'][0]
        logger.info(f"Found YouTube video: {video['title']}")
        return video['url'], video['title']

# Helper functions
async def search_youtube(query: str) -> tuple[str, str]:
    return  await search_youtube_ytdlp(query)

async def download_audio(youtube_url: str) -> tuple[Path, Path]:
    """Download audio from YouTube URL and return the file path."""
    logger.info(f"Downloading audio from: {youtube_url}")
    temp_dir = Path(tempfile.mkdtemp(dir=r"G:/code\project\Next.js\localmusic\PythonServer\downloads"))
    uuid = str(uuid4())
    os.makedirs(temp_dir/uuid, exist_ok=True)
    logger.info(f"Temporary directory created: {temp_dir/uuid}")
    output_template = f"{temp_dir}/{uuid}.%(ext)s"
    logger.info(f"Output template: {output_template}")
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([youtube_url])
        path=Path(output_template)
        if not path.exists():
            raise HTTPException(status_code=404, detail="Audio file not found")
        logger.info(f"Audio downloaded: {path}")
        mp3_file = next(path.glob(f"{uuid}.*"))
        return mp3_file, temp_dir
    except Exception as e:
        shutil.rmtree(temp_dir)
        raise HTTPException(status_code=500, detail=f"Failed to download audio: {str(e)}")

async def search_and_download_audio(query: str) -> tuple[Path, Path]:
    """Download audio from YouTube URL and return the file path."""
    logger.info(f"Downloading audio from: {query}")
    # First get the YouTube URL
    youtube_url, _ = await search_youtube(query)
    
    # Unique identifier for the download folder
    uid = str(uuid4())
    temp_dir = Path("temp_dir")
    download_path = temp_dir / uid
    os.makedirs(download_path, exist_ok=True)

    # Options for yt-dlp
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': str(download_path / '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'quiet': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
        
        # Find the downloaded MP3 file
        mp3_files = list(download_path.glob('*.mp3'))
        if not mp3_files:
            raise HTTPException(status_code=404, detail="MP3 file not found")
        
        return mp3_files[0], temp_dir
    except Exception as e:
        shutil.rmtree(temp_dir)
        raise HTTPException(status_code=500, detail=f"Failed to download audio: {str(e)}")

async def fetch_spotify_metadata(query: str) -> dict:
    """Fetch song metadata from Spotify."""
    logger.info(f"Fetching Spotify metadata for: {query}")
    try:
        result = sp.search(q=query, type='track', limit=1)
        if not result['tracks']['items']:
            raise HTTPException(status_code=404, detail="No Spotify metadata found")
        
        item = result['tracks']['items'][0]
        print(item)
        return {
            "title": item['name'],
            "artist": item['artists'][0]['name'],
            "album": item['album']['name'],
            "year": item['album']['release_date'][:4],
            "cover_url": item['album']['images'][0]['url']
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch Spotify metadata: {str(e)}")

async def embed_metadata(file_path: Path, metadata: dict, lyrics: str) -> None:
    """Embed metadata and lyrics into the MP3 file."""
    logger.info(f"Embedding metadata into: {file_path}")
    try:
        audio = MP3(file_path, ID3=ID3)
        try:
            audio.add_tags()
        except:
            pass

        audio.tags.add(TIT2(encoding=3, text=metadata["title"]))
        audio.tags.add(TPE1(encoding=3, text=metadata["artist"]))
        audio.tags.add(TALB(encoding=3, text=metadata["album"]))
        audio.tags.add(TYER(encoding=3, text=metadata["year"]))
        audio.tags.add(USLT(encoding=3, desc="Lyrics", text=lyrics))

        async with httpx.AsyncClient() as client:
            response = await client.get(metadata["cover_url"])
            if response.status_code == 200:
                audio.tags.add(APIC(
                    encoding=3,
                    mime='image/jpeg',
                    type=3,
                    desc='Cover',
                    data=response.content
                ))

        audio.save()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to embed metadata: {str(e)}")

async def upload_to_cloudinary(file_path: Path, metadata: dict) -> tuple[str, str]:
    """Upload file to Cloudinary and return URL and public ID."""
    logger.info(f"Uploading to Cloudinary: {file_path}")
    try:
        response = cloudinary.uploader.upload(
            str(file_path),
            public_id=f"{metadata["title"]}_{metadata["artist"]}_{metadata["album"]}_{metadata["year"]}_{str(uuid4())}",
            resource_type="raw",
            folder="AUDIO@FILES"
        )
        print(response["secure_url"], response["public_id"])
        return response["secure_url"], response["public_id"]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to upload to Cloudinary: {str(e)}")

# FastAPI routes
@app.post("/process-audio", response_model=ProcessResponse)
async def process_audio(request: ProcessRequest):
    """Process audio from YouTube with metadata and lyrics."""
    try:
        print(request)
        youtube_url = await search_youtube(request.query)
        # mp3_path, temp_dir = await download_audio(youtube_url)
        mp3_path, temp_dir = await search_and_download_audio(request.query)
        # mp3_path = r'G:\code\project\Next.js\localmusic\PythonServer\downloads\tmpr_sg__i2\e04ad3ad-2789-499c-9aa5-75a9211d2d60.＂Tum Hi Ho Aashiqui 2＂ Full Video Song HD ｜ Aditya Roy Kapur, Shraddha Kapoor ｜ Music - Mithoon.mp3'
        metadata = await fetch_spotify_metadata(request.query)
        await embed_metadata(mp3_path, metadata, request.lyrics)
        cloud_url, public_id = await upload_to_cloudinary(mp3_path,metadata)

        # Cleanup
        shutil.rmtree(temp_dir)

        return ProcessResponse(
            youtube_url=youtube_url,
            public_id= public_id,
            cloudinary_url= cloud_url
        )

    except HTTPException as e:
        raise e
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/process-song", response_model=ProcessResponse)
async def process_song(query: str = "tum hi ho", lyrics: str = "lyrics"):
    """Process a song with a simple GET request."""
    return await process_audio(ProcessRequest(query=query, lyrics=lyrics))

if __name__ == "__main__":
    import uvicorn
    port=int(os.environ.get("PORT",8000))
    uvicorn.run(app,host="0.0.0.0", port=port)
