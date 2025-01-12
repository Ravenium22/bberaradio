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
    'extract_flat': True,
    'quiet': True,
    'no_warnings': True
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
        self.load_tracks()
        self.now_playing_message = None
        self.last_activity_update = None

    def load_tracks(self):
        """Load both local tracks and tracks from tracks.json"""
        # Load local tracks
        if not os.path.exists(self.music_path):
            os.makedirs(self.music_path)

        for file in os.listdir(self.music_path):
            if file.endswith('.mp3'):
                try:
                    audio = EasyID3(os.path.join(self.music_path, file))
                    duration = MP3(os.path.join(self.music_path, file)).info.length
                    self.tracks.append(Track(
                        title=audio.get('title', [os.path.splitext(file)[0]])[0],
                        artist=audio.get('artist', ['Unknown'])[0],
                        duration=duration,
                        source_type='local',
                        source_path=os.path.join(self.music_path, file)
                    ))
                except Exception as e:
                    print(f"Error loading track {file}: {e}")

        # Load SoundCloud tracks from JSON
        try:
            if os.path.exists('tracks.json'):
                with open('tracks.json', 'r') as f:
                    saved_tracks = json.load(f)
                for track_data in saved_tracks:
                    self.tracks.append(Track(**track_data))
        except Exception as e:
            print(f"Error loading tracks.json: {e}")

    def save_tracks(self):
        """Save tracks to JSON (only SoundCloud tracks)"""
        tracks_to_save = [
            {
                'title': track.title,
                'artist': track.artist,
                'duration': track.duration,
                'source_type': track.source_type,
                'source_path': track.source_path,
                'url': track.url
            }
            for track in self.tracks if track.source_type == 'soundcloud'
        ]
        with open('tracks.json', 'w') as f:
            json.dump(tracks_to_save, f, indent=2)

    async def add_soundcloud_track(self, url):
        """Add a SoundCloud track to the library"""
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = await bot.loop.run_in_executor(None, lambda: ydl.extract_info(url, download=False))
                
                track = Track(
                    title=info.get('title', 'Unknown'),
                    artist=info.get('uploader', 'Unknown'),
                    duration=info.get('duration', 0),
                    source_type='soundcloud',
                    source_path=url,
                    url=url
                )
                self.tracks.append(track)
                self.save_tracks()
                return track
        except Exception as e:
            print(f"Error adding SoundCloud track: {e}")
            return None

    def shuffle_tracks(self):
        """Shuffle all available tracks"""
        self.track_queue = deque(random.sample(self.tracks, len(self.tracks)))

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

    async def play_track(self, track):
        """Play a specific track"""
        if not self.voice_client:
            return

        try:
            if track.source_type == 'local':
                source = discord.FFmpegPCMAudio(track.source_path)
            else:  # soundcloud
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = await bot.loop.run_in_executor(None, lambda: ydl.extract_info(track.url, download=False))
                    source = discord.FFmpegPCMAudio(info['url'], **{
                        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                        'options': '-vn'
                    })

            self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
                self.play_next(e), bot.loop).result())
            
            await self.update_presence(track)

            # Update now playing message
            if self.now_playing_message:
                try:
                    await self.now_playing_message.edit(
                        content=f"🎵 Now Playing: {track.title} - {track.artist}")
                except discord.NotFound:
                    pass

        except Exception as e:
            print(f"Error playing track: {e}")
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

@bot.command(name='add')
async def add(ctx, url):
    """Add a SoundCloud track to the library"""
    await ctx.send("Adding track, please wait...")
    track = await player.add_soundcloud_track(url)
    if track:
        await ctx.send(f"Added: {track.title} - {track.artist}")
    else:
        await ctx.send("Failed to add track.")

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

# Run the bot
if __name__ == "__main__":
    maintain_connection.start()
    bot.run(os.getenv('DISCORD_TOKEN'))