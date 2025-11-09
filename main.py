import os
import json
import time
import random
import string
import traceback
import sqlite3
import requests
import discord
from discord.ext import commands
from discord import app_commands
from discord.ext.commands import CommandNotFound
from discord.ui import View, Button
from dotenv import load_dotenv
from datetime import datetime, timedelta, timezone
import asyncio

# ------------------------------
# Logging Setup
# ------------------------------
def log_output(message: str, console_output=False):
    """Log messages to file and optionally to console"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_entry = f"[{timestamp}] {message}\n"
    
    # Always write to file
    with open("misc/output.txt", "a", encoding="utf-8") as f:
        f.write(log_entry)
    
# ------------------------------
# Load environment variables
# ------------------------------
load_dotenv("misc/.env")
DISCORD_TOKEN, = (
    os.getenv("DISCORD_TOKEN"),
)

# ------------------------------
# Bot Configuration
# ------------------------------
intents = discord.Intents.default()
intents.message_content = intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)
 

# ------------------------------
# Error logging
# ------------------------------
def log_error(error: Exception, command_name: str = ""):
    error_time = datetime.now()
    with open("Misc/error_logger.txt", "a", encoding="utf-8") as f:
        f.write(f"\n--- {error_time} ---\n")
        if command_name:
            f.write(f"Command: {command_name}\n")
        f.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
        f.write("\n")

# ------------------------------

# ------------------------------
# Bot Events
# ------------------------------
@bot.event
async def on_ready():
    try:
        log_output(f"Bot initialized: {bot.user} (ID: {bot.user.id})")
        
        GUILD_ID = 1016748575289516122
        
        # Guild command synchronization
        guild = discord.Object(id=GUILD_ID)
        await bot.tree.sync(guild=guild)
        log_output("Guild slash commands synchronized")
        
        # Global command synchronization
        await bot.tree.sync()
        log_output("Global slash commands synchronized")
        
        # Command verification
        guild_commands = await bot.tree.fetch_commands(guild=guild)
        global_commands = await bot.tree.fetch_commands()
        
        log_output(f"Guild commands registered: {len(guild_commands)}")
        log_output(f"Global commands registered: {len(global_commands)}")
        
    except Exception as e:
        log_output(f"Error during initialization: {e}")
        log_error(e, "on_ready")

# ------------------------------
# !ping command -- Tell ping and latency of the bot
# ------------------------------
allowed_channel_id = [1376614270892118128,1370146502705418352]
@bot.command()
async def ping(ctx):
    try:
        if ctx.channel.id not in allowed_channel_id:
            return
        
        latency = round(bot.latency * 1000)
        embed = discord.Embed(
            title="System Status",
            description=f"Bot operational and responsive.\n**Latency:** {latency}ms",
            color=discord.Color.green(),
            timestamp=datetime.now()
        ).set_footer(text=f"Requested by {ctx.author}", icon_url=ctx.author.display_avatar.url)
        
        msg = await ctx.send(embed=embed)
        await msg.delete(delay=20)
        
    except Exception as e:
        await ctx.send("Error processing command")
        log_error(e, "ping")

# ------------------------------
