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
import random
import spacy

load_dotenv()
TOKEN = os.getenv('DISCORD_TOKEN')
GUILD = os.getenv('DISCORD_GUILD')
GUILD_ID = os.getenv('DISCORD_GUILD_ID')
CHANNEL = os.getenv('DISCORD_CHANNEL')

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

def yoda_transform(text):

    nlp = spacy.load("en_core_web_sm")
    suffixes = [
        "Hmm.", "Yes, hmmm.", "Strong with the Force, this one is.", "Mmm.", "Meditate on this, I will.", "The path to the dark side, that is.", "Powerful you have become.", "Do or do not, there is no try.", "Much to learn, you still have.", "Ready, are you?", "Clouded, this one’s future is.", "Begun, the Clone War has.", "A Jedi craves not these things.", "Always in motion is the future.", "Control, control, you must learn control!", "That is why you fail.", "Hmm. Difficult to see. Always in motion is the future.", "You must unlearn what you have learned.", "Adventure. Excitement. A Jedi craves not these things.", "Wars not make one great.", "Judge me by my size, do you?", "When nine hundred years old you reach, look as good you will not.", "Patience you must have, my young Padawan.", "Truly wonderful, the mind of a child is.", "Mind what you have learned. Save you it can.", "Much fear I sense in you.", "Help you I can, yes.", "Into exile I must go. Failed, I have.", "Hmm. Yes. A flaw more and more common this is.", "Twisted by the dark side, young Skywalker has become.", "The greatest teacher, failure is.", "Fear is the path to the dark side.", "Anger leads to hate, hate leads to suffering.", "Seen it, I have.", "Foreseen this, I have.", "Dark times are ahead.", "If so powerful you are, why leave?", "Long have I watched.", "Yessss.", "Strong am I with the Force.", "In a dark place we find ourselves.", "Hope is not lost.", "To answer power with power, the Jedi way this is not.", "Truly the dark side clouds everything.", "Rest I need, yes.", "Take care of you, I will.", "Trust the Force, you must.", "Listen you must.", "Clear your mind must be, if you are to discover the real villains behind this plot.", "Over many paths the Force flows.", "Your focus determines your reality."
    ]
    sentences = re.split(r'([.!?])', text)
    result = []
    for i in range(0, len(sentences)-1, 2):
        sentence = sentences[i].strip()
        punct = sentences[i+1]
        doc = nlp(sentence)
        words = [token.text for token in doc]
        verb_idx = -1
        for idx in range(len(doc)-1, -1, -1):
            if doc[idx].pos_ == "VERB":
                verb_idx = idx
                break
        if verb_idx != -1 and verb_idx < len(words)-1:
            yoda = words[verb_idx:] + words[:verb_idx]
            yoda_sentence = ', '.join([' '.join(yoda[:len(words)-verb_idx]), ' '.join(yoda[len(words)-verb_idx:])]).capitalize() + punct
        else:
            yoda_sentence = sentence + punct
        result.append(yoda_sentence)
    if len(sentences) % 2 == 1:
        result.append(sentences[-1])
    yoda_text = ' '.join(result)
    if random.random() < 0.8:
        yoda_text += ' ' + random.choice(suffixes)
    return yoda_text

class MyClient(discord.Client):
    async def setup_hook(self):
        self.reddit = asyncpraw.Reddit('bot1')
        self.subreddit = await self.reddit.subreddit("countwithchickenlady")
        self.bg_task = self.loop.create_task(link_to_new_posts(self))
        self.image_of_day_task = self.loop.create_task(image_of_day_task(self))
        self.tree = discord.app_commands.CommandTree(self)
        @self.tree.command(name="yoda", description="Make your text sound like Yoda!")
        @discord.app_commands.describe(text="The text to Yoda-ify")
        async def yoda_command(interaction: discord.Interaction, text: str):
            yoda_text = yoda_transform(text)
            await interaction.response.send_message(yoda_text)
        # Do not sync here, will sync in on_ready

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
                    cursor.execute("INSERT INTO posts (id) VALUES (?)", (post.id,))
                    conn.commit()
                    for guild in client.guilds:
                        if guild.name == GUILD:
                            for channel in guild.channels:
                                if channel.name == CHANNEL:
                                    await channel.send('u/{author} has counted to [{title}](https://www.reddit.com/r/countwithchickenlady/comments/{id}/).'.format(author=post.author.name.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})) if post.author else '[deleted]',title=post.title.translate(str.maketrans({'_':  r'\_', '*':  r'\*', '~':  r'\~'})),id=post.id))
            conn.close()
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
            for guild in client.guilds:
                if guild.name == GUILD:
                    for channel in guild.channels:
                        if channel.name == 'daily-bot-post':
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
                                        await top_msg.reply(f"This is the image I will post today, decided by your votes! Posted as [{new_number}](https://www.reddit.com/r/countwithchickenlady/comments/{submission.id}/)", mention_author=True)
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

    print("Message posted in daily-bot-post channel")

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
            await message.add_reaction('✅')
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
    for guild in client.guilds:
        if guild.name == GUILD:
            for channel in guild.channels:
                if channel.name == 'daily-bot-post' and isinstance(channel, discord.TextChannel):
                    async for message in channel.history(limit=100, oldest_first=True):
                        if message.author != guild.me:
                            await on_message(message)
                            
client.run(TOKEN)