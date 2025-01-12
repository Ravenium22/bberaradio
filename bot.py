import discord
from discord.ext import commands, tasks
import os
import json
import asyncio
from collections import deque
import random
from mutagen.mp3 import MP3
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class MusicPlayer:
    def __init__(self):
        self.voice_client = None
        self.current_track = None
        self.track_queue = deque()
        self.is_playing = False
        self.tracks_dir = "private_tracks"
        self.tracks = []
        self.load_tracks()
        self.now_playing_message = None

    def load_tracks(self):
        """Load all tracks from the private_tracks directory"""
        if not os.path.exists(self.tracks_dir):
            os.makedirs(self.tracks_dir)
            print(f"Created {self.tracks_dir} directory")
            return

        for file in os.listdir(self.tracks_dir):
            if file.endswith(('.mp3', '.wav', '.ogg')):
                try:
                    track_path = os.path.join(self.tracks_dir, file)
                    # Get track duration if it's an MP3
                    duration = 0
                    if file.endswith('.mp3'):
                        audio = MP3(track_path)
                        duration = audio.info.length

                    self.tracks.append({
                        'title': os.path.splitext(file)[0],
                        'path': track_path,
                        'duration': duration
                    })
                except Exception as e:
                    print(f"Error loading track {file}: {e}")

        print(f"Loaded {len(self.tracks)} tracks")

    def shuffle_queue(self):
        """Shuffle all tracks and add to queue"""
        available_tracks = self.tracks.copy()
        random.shuffle(available_tracks)
        self.track_queue = deque(available_tracks)
        print(f"Shuffled {len(self.track_queue)} tracks")

    async def play_next(self, error=None):
        """Play the next track in queue"""
        if error:
            print(f"Error in playback: {error}")

        if not self.track_queue:
            self.shuffle_queue()

        if self.track_queue and self.voice_client:
            self.current_track = self.track_queue.popleft()
            try:
                source = discord.FFmpegPCMAudio(self.current_track['path'])
                self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
                    self.play_next(e), bot.loop))
                
                # Update now playing message
                if self.now_playing_message:
                    try:
                        await self.now_playing_message.edit(
                            content=f"🎵 Now Playing: {self.current_track['title']}")
                    except discord.NotFound:
                        pass

                # Update bot status
                activity = discord.Activity(
                    type=discord.ActivityType.listening,
                    name=self.current_track['title']
                )
                await bot.change_presence(activity=activity)

            except Exception as e:
                print(f"Error playing track: {e}")
                await self.play_next()

player = MusicPlayer()

@bot.event
async def on_ready():
    print(f'{bot.user} is ready!')
    print(f"Loaded {len(player.tracks)} tracks")
    player.shuffle_queue()

@bot.command(name='start')
async def start(ctx):
    """Start playing music"""
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
    """Stop playing music"""
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.stop()
        player.is_playing = False
        await bot.change_presence(activity=None)
        await ctx.send("Playback stopped.")

@bot.command(name='skip')
async def skip(ctx):
    """Skip current track"""
    if player.voice_client and player.voice_client.is_playing():
        player.voice_client.stop()
        await ctx.send("⏭️ Skipping to next track...")

@bot.command(name='queue', aliases=['q'])
async def queue(ctx):
    """Show next few tracks in queue"""
    if not player.track_queue:
        await ctx.send("Queue is empty.")
        return

    queue_list = list(player.track_queue)[:5]  # Show next 5 tracks
    queue_text = "📋 Upcoming tracks:\n"
    for i, track in enumerate(queue_list, 1):
        queue_text += f"{i}. {track['title']}\n"

    await ctx.send(queue_text)

@bot.command(name='tracks')
async def list_tracks(ctx):
    """List all available tracks"""
    if not player.tracks:
        await ctx.send("No tracks available.")
        return

    tracks_text = "📀 Available tracks:\n"
    for i, track in enumerate(player.tracks, 1):
        duration = int(track['duration']) if track['duration'] else 'Unknown'
        tracks_text += f"{i}. {track['title']} ({duration}s)\n"
        if i % 20 == 0:  # Split into multiple messages if too long
            await ctx.send(tracks_text)
            tracks_text = ""
    
    if tracks_text:
        await ctx.send(tracks_text)

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