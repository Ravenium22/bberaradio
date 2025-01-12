import discord
from discord.ext import commands, tasks
import os
import json
import asyncio
from collections import deque
import random
from mutagen.mp3 import MP3
from mutagen.easyid3 import EasyID3
import yt_dlp
from datetime import datetime
from dotenv import load_dotenv
import sys

# Load environment variables
load_dotenv()

# Get token and validate
TOKEN = os.getenv('DISCORD_TOKEN')
if not TOKEN:
    print("Error: No Discord token found. Make sure DISCORD_TOKEN is set in your environment variables.")
    sys.exit(1)

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

# YT-DLP configuration for SoundCloud
ydl_opts = {
    'format': 'bestaudio/best',
    'postprocessors': [{
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'opus',
    }],
    'extract_flat': 'in_playlist',
    'quiet': True,
    'no_warnings': True,
    'force_generic_extractor': False
}

class Track:
    def __init__(self, title, artist, duration, source_type, source_path, url=None):
        self.title = title
        self.artist = artist
        self.duration = duration
        self.source_type = source_type  # 'local' or 'soundcloud'
        self.source_path = source_path
        self.url = url

class MusicPlayer:
    def __init__(self):
        self.voice_client = None
        self.current_track = None
        self.track_queue = deque()
        self.is_playing = False
        self.music_path = "music"
        self.tracks = []
        self.playlists = {}  # Store playlists
        self.now_playing_message = None
        self.last_activity_update = None
        print("Music Player initialized")
        self.load_tracks()
        self.load_playlists()

    def load_tracks(self):
        """Load tracks from tracks.json"""
        try:
            if os.path.exists('tracks.json'):
                with open('tracks.json', 'r') as f:
                    track_data = json.load(f)
                    for track in track_data:
                        self.tracks.append(Track(**track))
                print(f"Loaded {len(self.tracks)} tracks from tracks.json")
        except Exception as e:
            print(f"Error loading tracks: {e}")
            self.tracks = []

    def save_tracks(self):
        """Save tracks to tracks.json"""
        try:
            tracks_to_save = [
                {
                    'title': track.title,
                    'artist': track.artist,
                    'duration': track.duration,
                    'source_type': track.source_type,
                    'source_path': track.source_path,
                    'url': track.url
                }
                for track in self.tracks
            ]
            with open('tracks.json', 'w') as f:
                json.dump(tracks_to_save, f, indent=2)
            print("Tracks saved successfully")
        except Exception as e:
            print(f"Error saving tracks: {e}")

    def load_playlists(self):
        """Load playlists from playlists.json"""
        try:
            if os.path.exists('playlists.json'):
                with open('playlists.json', 'r') as f:
                    self.playlists = json.load(f)
                print(f"Loaded playlists: {list(self.playlists.keys())}")
        except Exception as e:
            print(f"Error loading playlists: {e}")
            self.playlists = {}

    def save_playlists(self):
        """Save playlists to playlists.json"""
        try:
            with open('playlists.json', 'w') as f:
                json.dump(self.playlists, f, indent=2)
            print("Playlists saved successfully")
        except Exception as e:
            print(f"Error saving playlists: {e}")

    async def add_playlist(self, url, name=None):
        """Add all tracks from a playlist"""
        print(f"Attempting to add playlist from URL: {url}")
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                print("Extracting playlist info...")
                info = await bot.loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                if 'entries' not in info:
                    print("No entries found in playlist")
                    return False, "No tracks found in playlist"

                playlist_name = name or info.get('title', 'Unnamed Playlist')
                track_list = []

                print(f"Processing {len(info['entries'])} tracks...")
                for entry in info['entries']:
                    if entry:
                        track = Track(
                            title=entry.get('title', 'Unknown'),
                            artist=entry.get('uploader', 'Unknown'),
                            duration=entry.get('duration', 0),
                            source_type='soundcloud',
                            source_path=entry['url'],
                            url=entry['url']
                        )
                        track_list.append({
                            'title': track.title,
                            'artist': track.artist,
                            'duration': track.duration,
                            'source_type': track.source_type,
                            'source_path': track.source_path,
                            'url': track.url
                        })
                        self.tracks.append(track)

                self.playlists[playlist_name] = track_list
                self.save_playlists()
                print(f"Added playlist: {playlist_name} with {len(track_list)} tracks")
                return True, f"Added playlist: {playlist_name} with {len(track_list)} tracks"

        except Exception as e:
            print(f"Error adding playlist: {e}")
            return False, f"Error adding playlist: {str(e)}"

    def shuffle_tracks(self):
        """Shuffle all available tracks"""
        available_tracks = self.tracks.copy()
        random.shuffle(available_tracks)
        self.track_queue = deque(available_tracks)
        print(f"Shuffled {len(self.track_queue)} tracks")

    async def update_presence(self, track):
        """Update bot's activity status"""
        if track and (not self.last_activity_update or 
                     (datetime.now() - self.last_activity_update).seconds > 5):
            activity = discord.Activity(
                type=discord.ActivityType.listening,
                name=f"{track.title} - {track.artist}"
            )
            await bot.change_presence(activity=activity)
            self.last_activity_update = datetime.now()

    async def load_playlist(self, name):
        """Load a specific playlist into the queue"""
        print(f"Loading playlist: {name}")
        if name not in self.playlists:
            print(f"Playlist not found: {name}")
            return False, "Playlist not found"

        try:
            playlist_tracks = self.playlists[name]
            self.track_queue.clear()
            
            for track_data in playlist_tracks:
                track = Track(**track_data)
                self.track_queue.append(track)

            print(f"Loaded {len(self.track_queue)} tracks from playlist: {name}")
            random.shuffle(list(self.track_queue))
            return True, f"Loaded {len(self.track_queue)} tracks from playlist: {name}"
        except Exception as e:
            print(f"Error loading playlist {name}: {e}")
            return False, f"Error loading playlist: {str(e)}"

    async def play_track(self, track):
        """Play a specific track"""
        if not self.voice_client:
            print("No voice client available")
            return

        try:
            print(f"Playing track: {track.title} - {track.artist}")
            if track.source_type == 'soundcloud':
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    print("Extracting track info...")
                    info = await bot.loop.run_in_executor(None, lambda: ydl.extract_info(track.url, download=False))
                    stream_url = info['url']
                    print("Got stream URL")
                    source = discord.FFmpegPCMAudio(stream_url, **{
                        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                        'options': '-vn'
                    })
            else:
                print("Playing local file")
                source = discord.FFmpegPCMAudio(track.source_path)

            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(e), bot.loop))
            
            await self.update_presence(track)
            print(f"Now playing: {track.title}")

            if self.now_playing_message:
                try:
                    await self.now_playing_message.edit(
                        content=f"🎵 Now Playing: {track.title} - {track.artist}")
                except discord.NotFound:
                    pass

        except Exception as e:
            print(f"Error playing track {track.title}: {e}")
            await self.play_next()

    async def play_next(self, error=None):
        """Play the next track in queue"""
        if error:
            print(f"Error in playback: {error}")

        if not self.track_queue:
            self.shuffle_tracks()

        if self.track_queue and self.voice_client:
            self.current_track = self.track_queue.popleft()
            await self.play_track(self.current_track)

player = MusicPlayer()

@bot.event
async def on_ready():
    print(f'{bot.user} is ready!')
    player.shuffle_tracks()

@bot.command(name='addplaylist', aliases=['apl'])
async def add_playlist(ctx, url, *, name=None):
    """Add a SoundCloud playlist to the library"""
    message = await ctx.send("Adding playlist, please wait...")
    success, result = await player.add_playlist(url, name)
    await message.edit(content=result)

@bot.command(name='playlist', aliases=['pl'])
async def load_playlist(ctx, *, name):
    """Load and play a saved playlist"""
    success, result = await player.load_playlist(name)
    if success:
        await ctx.send(result)
        if not player.is_playing:
            await start(ctx)
    else:
        await ctx.send(result)

@bot.command(name='playlists', aliases=['pls'])
async def list_playlists(ctx):
    """List all saved playlists"""
    if not player.playlists:
        await ctx.send("No playlists saved.")
        return

    playlist_text = "📋 Saved playlists:\n"
    for name, tracks in player.playlists.items():
        playlist_text += f"- {name} ({len(tracks)} tracks)\n"
    await ctx.send(playlist_text)

@bot.command(name='start')
async def start(ctx):
    """Start the 24/7 music player"""
    if not ctx.author.voice:
        await ctx.send("You must be in a voice channel!")
        return

    channel = ctx.author.voice.channel
    
    if not player.voice_client:
        player.voice_client = await channel.connect()
    
    if not player.is_playing:
        player.is_playing = True
        player.now_playing_message = await ctx.send("🎵 Starting playback...")
        await player.play_next()

@bot.command(name='stop')
async def stop(ctx):
    """Stop the music player"""
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.stop()
        player.is_playing = False
        await bot.change_presence(activity=None)
        await ctx.send("Playback stopped.")

@bot.command(name='skip')
async def skip(ctx):
    """Skip the current track"""
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.stop()
        await ctx.send("⏭️ Skipping to next track...")

@bot.command(name='nowplaying', aliases=['np'])
async def now_playing(ctx):
    """Display current track information"""
    if player.current_track and player.is_playing:
        await ctx.send(f"🎵 Now Playing: {player.current_track.title} - {player.current_track.artist}")
    else:
        await ctx.send("Nothing is playing right now.")

@bot.command(name='queue', aliases=['q'])
async def queue(ctx):
    """Display next few tracks in queue"""
    if not player.track_queue:
        await ctx.send("Queue is empty.")
        return

    queue_list = list(player.track_queue)[:5]
    queue_text = "📋 Upcoming tracks:\n"
    for i, track in enumerate(queue_list, 1):
        queue_text += f"{i}. {track.title} - {track.artist}\n"

    await ctx.send(queue_text)

@tasks.loop(minutes=30)
async def maintain_connection():
    """Keep the bot connection alive"""
    if player.voice_client and not player.voice_client.is_playing():
        await player.play_next()

async def main():
    try:
        async with bot:
            maintain_connection.start()
            await bot.start(TOKEN)
    except Exception as e:
        print(f"Error starting bot: {e}")
        sys.exit(1)

if __name__ == "__main__":
    print("Starting bot...")
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Bot shutdown by user.")
    except Exception as e:
        print(f"Fatal error: {e}")
        sys.exit(1)