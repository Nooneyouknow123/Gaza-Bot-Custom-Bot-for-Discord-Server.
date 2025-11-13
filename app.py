import discord

from discord.ext import commands

import os

import traceback

from datetime import datetime

# -------------------- TIMESTAMP --------------------

def timestamp():

    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

# -------------------- INTENTS --------------------

intents = discord.Intents.default()

intents.guilds = True

intents.members = True

intents.messages = True

intents.message_content = True

intents.reactions = True

intents.emojis_and_stickers = True

intents.voice_states = True

intents.guild_messages = True

intents.guild_reactions = True

# -------------------- BOT SETUP --------------------

bot = commands.Bot(command_prefix=".", intents=intents, help_command=None)

# -------------------- COMMAND: list_commands --------------------

@bot.command()

async def list_commands(ctx):

    cmds = [cmd.name for cmd in bot.commands]

    await ctx.send(f"Available Commands: {', '.join(cmds)}")

# -------------------- RELOAD COMMAND --------------------

allowed_users = [951863963132506232, 1274667778300706866]

@bot.command()

async def reload(ctx, cog: str = None):

    if ctx.author.id not in allowed_users:

        return await ctx.send("You are not allowed to use this command.", delete_after=5)

    if not cog:

        return await ctx.send("Please specify a cog name.", delete_after=5)

    try:

        await bot.reload_extension(f"cogs.{cog}")

        await ctx.send(f"✅ Successfully reloaded cog: **{cog}**")

        print(f"{timestamp()} Reloaded: {cog}")

    except Exception as e:

        await ctx.send(f"❌ Failed to reload `{cog}`: {e}")

        traceback.print_exc()

# -------------------- LOAD ALL COGS --------------------

async def load_cogs():

    if not os.path.exists("cogs"):

        print(f"{timestamp()} ❌ Folder 'cogs' not found.")

        return

    for file in os.listdir("cogs"):

        if file.endswith(".py"):

            name = file[:-3]

            try:

                await bot.load_extension(f"cogs.{name}")

                print(f"{timestamp()} ✅ Loaded cog: {name}")

            except Exception as e:

                print(f"{timestamp()} ❌ Failed to load {name}: {e}")

# -------------------- ERROR HANDLER --------------------

@bot.event

async def on_command_error(ctx, error):

    if isinstance(error, commands.CommandNotFound):

        return

    embed = discord.Embed(

        title="⚠️ Command Error",

        color=discord.Color.red(),

        timestamp=datetime.utcnow()

    )

    # Specific error handling

    if isinstance(error, commands.MissingPermissions):

        embed.description = "🚫 **You don't have permission to use this command.**"

    elif isinstance(error, commands.BotMissingPermissions):

        embed.description = "🤖 **I don't have enough permissions to perform this action.**"

    elif isinstance(error, commands.MissingRole):

        embed.description = f"🔒 **You need the `{error.missing_role}` role to use this command.**"

    elif isinstance(error, commands.MissingAnyRole):

        roles = ", ".join(error.missing_roles)

        embed.description = f"🔒 **You need one of these roles to use this command:** `{roles}`"

    elif isinstance(error, commands.MissingRequiredArgument):

        embed.description = "⚠️ **Missing required argument!** Please check the command usage."

    elif isinstance(error, commands.BadArgument):

        embed.description = "⚠️ **Invalid argument provided!** Please check your input."

    elif isinstance(error, commands.CommandOnCooldown):

        embed.description = f"⏳ **This command is on cooldown. Try again in `{error.retry_after:.1f}` seconds.**"

    elif isinstance(error, commands.NoPrivateMessage):

        embed.description = "🏠 **This command can only be used inside a server (not in DMs).**"

    elif isinstance(error, commands.NotOwner):

        embed.description = "🛑 **Only the bot owner can use this command.**"

    elif isinstance(error, commands.CheckFailure):

        embed.description = "🚫 **You failed a check required to run this command.**"

    elif isinstance(error, commands.DisabledCommand):

        embed.description = "⚒️ **This command has been disabled by the bot owner.**"

    elif isinstance(error, commands.CommandInvokeError):

        embed.description = f"💥 **An unexpected error occurred while running the command.**\n```{error.original}```"

    else:

        embed.description = f"❌ **An unknown error occurred.**\n```{error}```"

    embed.set_footer(text=f"Command: {ctx.command} | User: {ctx.author}")

    try:

        await ctx.send(embed=embed, delete_after=10)

    except discord.Forbidden:

        print(f"{timestamp()} ❌ Could not send error message (missing permissions).")

    print(f"{timestamp()} ⚠️ Error in '{ctx.command}': {error}")

    traceback.print_exc()

# -------------------- READY EVENT --------------------

@bot.event

async def on_ready():

    await load_cogs()

    print(f"{timestamp()} Logged in as {bot.user} ({bot.user.id})")

    activity = discord.Activity(type=discord.ActivityType.listening, name="Utility Bot")

    await bot.change_presence(activity=activity)

    try:

        synced = await bot.tree.sync()

        print(f"{timestamp()} Synced {len(synced)} slash commands")

    except Exception as e:

        print(f"{timestamp()} Sync failed: {e}")

# -------------------- START BOT --------------------

if __name__ == "__main__":

    bot.run("put token here")

