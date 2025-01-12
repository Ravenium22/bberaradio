import discord
from discord.ext import commands, tasks
import os
import json
import asyncio
from collections import deque
import random
import motor.motor_asyncio
from bson.binary import Binary
from dotenv import load_dotenv
import io
import sys

# Load environment variables
load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
MONGODB_URL = os.getenv('MONGODB_URL')

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
        self.now_playing_message = None
        self.db_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URL)
        self.db = self.db_client.musicbot
        self.tracks_collection = self.db.tracks
        print("Music Player initialized")

    async def upload_track(self, file_path, title=None):
        """Upload a track to MongoDB"""
        try:
            with open(file_path, 'rb') as file:
                file_data = file.read()
                track_doc = {
                    'title': title or os.path.splitext(os.path.basename(file_path))[0],
                    'data': Binary(file_data),
                    'filename': os.path.basename(file_path),
                    'uploaded_at': datetime.utcnow()
                }
                await self.tracks_collection.insert_one(track_doc)
                print(f"Uploaded track: {track_doc['title']}")
                return True
        except Exception as e:
            print(f"Error uploading track: {e}")
            return False

    async def get_all_tracks(self):
        """Get all track metadata from MongoDB"""
        cursor = self.tracks_collection.find({}, {'title': 1, 'filename': 1})
        return await cursor.to_list(length=None)

    async def get_track_data(self, track_id):
        """Get track binary data from MongoDB"""
        track = await self.tracks_collection.find_one({'_id': track_id})
        if track:
            return track['data'], track['filename']
        return None, None

    async def play_track(self, track_id):
        """Play a track from MongoDB"""
        if not self.voice_client:
            return

        try:
            track_data, filename = await self.get_track_data(track_id)
            if track_data:
                # Save to temporary file
                temp_path = f"temp_{filename}"
                with open(temp_path, 'wb') as temp_file:
                    temp_file.write(track_data)

                source = discord.FFmpegPCMAudio(temp_path)
                self.voice_client.play(source, after=lambda e: asyncio.run_coroutine_threadsafe(
                    self.cleanup_and_play_next(e, temp_path), bot.loop))

                # Update now playing message
                if self.now_playing_message:
                    try:
                        await self.now_playing_message.edit(
                            content=f"🎵 Now Playing: {track['title']}")
                    except discord.NotFound:
                        pass

                # Update bot status
                activity = discord.Activity(
                    type=discord.ActivityType.listening,
                    name=track['title']
                )
                await bot.change_presence(activity=activity)

        except Exception as e:
            print(f"Error playing track: {e}")
            await self.play_next()

    async def cleanup_and_play_next(self, error, temp_path):
        """Clean up temporary file and play next track"""
        try:
            os.remove(temp_path)
        except:
            pass
        await self.play_next(error)

    async def play_next(self, error=None):
        """Play the next track in queue"""
        if error:
            print(f"Error in playback: {error}")

        if not self.track_queue:
            tracks = await self.get_all_tracks()
            if tracks:
                random.shuffle(tracks)
                self.track_queue = deque(tracks)

        if self.track_queue and self.voice_client:
            self.current_track = self.track_queue.popleft()
            await self.play_track(self.current_track['_id'])

player = MusicPlayer()

@bot.command(name='upload')
@commands.has_permissions(administrator=True)
async def upload(ctx):
    """Upload tracks to database"""
    if not ctx.message.attachments:
        await ctx.send("Please attach an audio file!")
        return

    for attachment in ctx.message.attachments:
        if attachment.filename.endswith(('.mp3', '.wav', '.ogg')):
            # Download file
            temp_path = f"temp_{attachment.filename}"
            await attachment.save(temp_path)
            
            # Upload to MongoDB
            success = await player.upload_track(temp_path, attachment.filename)
            
            # Clean up
            try:
                os.remove(temp_path)
            except:
                pass
            
            if success:
                await ctx.send(f"✅ Uploaded: {attachment.filename}")
            else:
                await ctx.send(f"❌ Failed to upload: {attachment.filename}")
        else:
            await ctx.send(f"❌ Invalid file type: {attachment.filename}")

@bot.command(name='tracks')
async def list_tracks(ctx):
    """List all available tracks"""
    tracks = await player.get_all_tracks()
    if not tracks:
        await ctx.send("No tracks available.")
        return

    tracks_text = "📀 Available tracks:\n"
    for i, track in enumerate(tracks, 1):
        tracks_text += f"{i}. {track['title']}\n"
        if i % 20 == 0:  # Split into multiple messages if too long
            await ctx.send(tracks_text)
            tracks_text = ""
    
    if tracks_text:
        await ctx.send(tracks_text)

# [Previous commands: start, stop, skip, queue remain the same]

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