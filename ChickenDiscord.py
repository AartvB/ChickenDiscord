import os
import discord
import asyncio
from dotenv import load_dotenv
import asyncpraw
import sqlite3
import time
import re
import aiohttp
import tempfile
import datetime

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
GUILD_ID = os.getenv('DISCORD_GUILD_ID')
CHANNEL = os.getenv('DISCORD_CHANNEL')

async def get_channel(client, channel_name):
    for guild in client.guilds:
        if guild.name == GUILD:
            for channel in guild.channels:
                if channel.name == channel_name:
                    return channel

async def get_last_announcement_time():
    conn = sqlite3.connect("ChickenCountingPosts.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS bot_meta (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("SELECT value FROM bot_meta WHERE key = ?", ("last_announcement_time",))
    row = cursor.fetchone()
    conn.close()
    if row:
        return float(row[0])
    return 0

async def set_last_announcement_time(timestamp):
    conn = sqlite3.connect("ChickenCountingPosts.db")
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS bot_meta (key TEXT PRIMARY KEY, value TEXT)")
    cursor.execute("INSERT OR REPLACE INTO bot_meta (key, value) VALUES (?, ?)", ("last_announcement_time", str(timestamp)))
    conn.commit()
    conn.close()

class MyClient(discord.Client):
    async def setup_hook(self):
        self.reddit = asyncpraw.Reddit('bot1')
        self.subreddit = await self.reddit.subreddit("countwithchickenlady")
        self.new_post_task = self.loop.create_task(link_to_new_posts(self))
        self.nsfw_check_task = self.loop.create_task(check_later_added_nsfw(self))
        self.image_of_day_task = self.loop.create_task(image_of_day_task(self))
        self.tree = discord.app_commands.CommandTree(self)

async def link_to_new_posts(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            print("New post check")
            conn = sqlite3.connect("ChickenCountingPosts.db")
            cursor = conn.cursor()
            posts = []
            async for post in client.subreddit.new(limit=25):
                posts.append(post)
            for post in reversed(posts):
                cursor.execute("SELECT COUNT(*) FROM posts WHERE id = ?", (post.id,))
                linked_to_post = cursor.fetchone()[0] > 0
                if not linked_to_post and int(post.created_utc) < int(time.time()) - 5*60:
                    print(f"Posting link to post {post.title} by {post.author.name if post.author else '[deleted]'}")
                    channel = await get_channel(client,CHANNEL)
                    sent_msg = await channel.send('u/{author} has counted to [{title}](https://www.reddit.com/r/countwithchickenlady/comments/{id}/).'.format(author=post.author.name.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})) if post.author else '[deleted]',title=post.title.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})),id=post.id))
                    cursor.execute("INSERT INTO posts (id, nsfw, message_id, post_time) VALUES (?, ?, ?, ?)",(post.id, post.over_18, str(sent_msg.id), post.created_utc))
                    conn.commit()
            conn.close()
        except Exception as e:
            print(e)
        await asyncio.sleep(60)

async def check_later_added_nsfw(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            print('New NSFW check')
            three_weeks_ago = int(time.time()) - 21 * 24 * 60 * 60
            conn = sqlite3.connect("ChickenCountingPosts.db")
            cursor = conn.cursor()
            cursor.execute("SELECT id, nsfw, message_id FROM posts WHERE post_time >= ?", (three_weeks_ago,))
            rows = cursor.fetchall()
            conn.close()
            for post_id, db_nsfw, message_id in rows:
                try:
                    post = await client.reddit.submission(id=post_id)
                    if int(post.over_18) and not db_nsfw:
                        print(f"Post {post_id} has been changed to NSFW")
                        channel = await get_channel(client,CHANNEL)
                        try:
                            msg = await channel.fetch_message(int(message_id))
                            if msg.embeds:
                                for idx, embed in enumerate(msg.embeds):
                                    new_embed = embed.copy()
                                    new_embed.title = '[Mature Content] '+new_embed.title
                                    new_embed.set_thumbnail(url='https://i.redd.it/o0h58lzmax6a1.png')
                                    await msg.edit(embed=new_embed)
                        except Exception as e:
                            print(f"Could not edit embed of message {message_id}: {e}")
                        # Update the database to reflect the NSFW status
                        conn = sqlite3.connect("ChickenTEST.db")
                        cursor = conn.cursor()
                        cursor.execute("UPDATE posts SET nsfw = 1 WHERE id = ?", (post_id,))
                        conn.commit()
                        conn.close()
                except Exception as e:
                    print(f"Error checking post {post_id}: {e}")
        except Exception as e:
            print(e)
        await asyncio.sleep(60)

async def image_of_day_task(client):
    await client.wait_until_ready()
    while not client.is_closed():
        try:
            last_time = await get_last_announcement_time()
            now = time.time()
            # Only run if at least 24 hours have passed since last_time
            if last_time and (now - last_time) < 24 * 60 * 60:
                await asyncio.sleep(60)  # Check again in 1 minute
                continue
            channel = await get_channel(client,'daily-bot-post')
            after_dt = datetime.datetime.fromtimestamp(last_time) if last_time else None
            messages = []
            async for msg in channel.history(limit=200, after=after_dt):
                image_attachments = [a for a in msg.attachments if a.content_type and a.content_type.startswith('image/')]
                if len(image_attachments) == 1:
                    checkmark = discord.utils.get(msg.reactions, emoji='✅')
                    count = checkmark.count if checkmark else 0
                    messages.append((msg, count, image_attachments[0]))
            if messages:
                top_msg, top_count, top_attachment = max(messages, key=lambda x: x[1])
                # Use asyncpraw to get the reference post and next number
                ref_post = await client.reddit.submission(id="1iulihu")
                ref_post_body = ref_post.selftext
                match = re.search(r'The next number should be: \[(\d+)\]', ref_post_body)
                if match:
                    new_number = match.group(1)
                    # Download the image
                    img_url = top_attachment.url
                    async with aiohttp.ClientSession() as session:
                        async with session.get(img_url) as img_resp:
                            img_bytes = await img_resp.read()
                    # Save image to a temporary file and submit to Reddit
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp_file:
                        tmp_file.write(img_bytes)
                        tmp_file_path = tmp_file.name
                    try:
                        submission = await client.subreddit.submit_image(new_number, tmp_file_path)
                        await submission.reply(
                            "This image was chosen by the people in our discord server. Want to have a vote on this? Join us [here](https://discord.gg/tefj2Xu9FP)!"
                        )
                        await top_msg.reply(f"This is the image I will post today, decided on by your votes! You can find it here in post [{new_number}](https://www.reddit.com/r/countwithchickenlady/comments/{submission.id}/). Post one ore more images below if you want your image to be posted by me tomorrow!", mention_author=True)
                        await set_last_announcement_time(now)
                    finally:
                        os.remove(tmp_file_path)
                else:
                    print("Could not determine the next number from the reference post.")
        except Exception as e:
            print(f"Error in image_of_day_task: {e}")
        await asyncio.sleep(60)

async def on_message(message):
    # Only process messages in the 'daily-bot-post' channel
    if message.channel.name != 'daily-bot-post':
        return
    # Ignore messages sent by this bot
    if message.author == message.guild.me:
        return

    # Check for attachments (images)
    image_attachments = [a for a in message.attachments if a.content_type and a.content_type.startswith('image/')]
    if len(image_attachments) != 1:
        try:
            await message.reply(
                "You can only post images in this channel. "
                "Please make sure to upload exactly one image per message. "
                "You can click the checkmark below posted images to vote on which one the bot will post today.",
                mention_author=True,
                delete_after=30
            )
        except Exception as e:
            print(f"Could not send reply to {message.author}: {e}")
        try:
            await message.delete()
            print("Message deleted: not exactly one image attachment")
        except Exception as e:
            print(f"Could not delete message: {e}")
        return
    # Add reaction if not already present (for both live and missed messages)
    try:
        reactions = [str(r.emoji) for r in message.reactions]
        if '✅' not in reactions:
            print("Message posted in daily-bot-post channel")
            await message.add_reaction('✅')
            await message.reply(f"{message.author.mention}, I added a ✅ for you! If you want to vote on your own image, you can also click the checkmark yourself.", mention_author=True, delete_after=15)
    except Exception as e:
        print(f"Could not add reaction: {e}")

intents = discord.Intents.default()
intents.message_content = True
client = MyClient(intents=intents)
client.on_message = on_message

# On ready, process missed messages while the bot was offline
@client.event
async def on_ready():
    print(f'Logged in as {client.user} (ID: {client.user.id})')
    print('------')
    print('Guilds the bot is in:')
    for guild in client.guilds:
        print(f"- {guild.name} (ID: {guild.id})")
    # Sync slash commands (global or to a specific guild for instant update)
    try:
        if GUILD_ID and GUILD_ID.isdigit():
            guild_obj = discord.Object(id=int(GUILD_ID))
            await client.tree.sync(guild=guild_obj)
            print(f"Slash commands synced to guild ID: {GUILD_ID}")
            commands = await client.tree.fetch_commands(guild=guild_obj)
        else:
            await client.tree.sync()
            print("Slash commands synced globally.")
            commands = await client.tree.fetch_commands()
        print("Registered slash commands:")
        for cmd in commands:
            print(f"- /{cmd.name}: {cmd.description}")
    except Exception as e:
        print(f"Error syncing slash commands: {e}")

    # Process missed messages in 'daily-bot-post'
    channel = await get_channel(client,'daily-bot-post')
    async for message in channel.history(limit=100, oldest_first=True):
        if message.author != guild.me:
            await on_message(message)
                            
client.run(TOKEN)