import discord
from discord.ext import commands
import os
import sys
import traceback
from datetime import datetime

# -------------------- LOGGING SETUP --------------------
def timestamp():
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

class LogRedirect:
    def __init__(self, filepath):
        self.filepath = filepath
        self.file = open(filepath, "a", encoding="utf-8")

    def write(self, message):
        # Ignore empty newline-only writes
        if message.strip():
            self.file.write(f"{timestamp()} {message}")
            self.file.flush()

    def flush(self):
        self.file.flush()

# Redirect stdout → console.txt and stderr → error.txt
sys.stdout = LogRedirect("console.txt")
sys.stderr = LogRedirect("error.txt")

# -------------------- INTENTS --------------------
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True
intents.guilds = True

# -------------------- BOT INSTANCE --------------------
bot = commands.Bot(command_prefix=".", intents=intents)

# -------------------- COMMANDS --------------------
@bot.command()
async def list_commands(ctx):
    commands_list = [command.name for command in bot.commands]
    await ctx.send(f"Available commands: {', '.join(commands_list)}")

import discord
from discord.ext import commands
import os
import traceback
from datetime import datetime

# -------------------- LOGGING SETUP --------------------
def timestamp():
    return datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")

# -------------------- INTENTS --------------------
intents = discord.Intents.default()
intents.members = True   # Required for detecting boosts (on_member_update)
intents.guilds = True
intents.messages = True
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

# -------------------- RELOAD COG COMMAND --------------------
allowed_users = [951863963132506232, 1274667778300706866]  # King + Fabio

@bot.command()
async def reload(ctx, cog: str = None):
    if ctx.author.id not in allowed_users:
        await ctx.send("You don't have permission to use this command.", delete_after=5)
        return

    if cog:
        try:
            await bot.reload_extension(f"cogs.{cog}")
            await ctx.send(f"✅ Reloaded cog: **{cog}**")
            print(f"{timestamp()} Reloaded cog: {cog}")
        except Exception as e:
            await ctx.send(f"❌ Failed to reload cog `{cog}`: {e}")
            print(f"{timestamp()} Failed to reload cog {cog}: {e}")
            traceback.print_exc()
    else:
        await ctx.send("Please specify a cog to reload.", delete_after=5)


# -------------------- COG LOADING --------------------
async def load_cogs():
    """
    Loads all cogs from the ./cogs directory.
    """
    cog_dir = "./cogs"
    if not os.path.exists(cog_dir):
        print(f"{timestamp()} Cog directory '{cog_dir}' does not exist.")
        return

    for filename in os.listdir(cog_dir):
        if filename.endswith(".py"):
            cog_name = filename[:-3]
            full_cog = f"cogs.{cog_name}"

            try:
                await bot.load_extension(full_cog)
                print(f"{timestamp()} ✅ Loaded cog: {cog_name}")
            except commands.ExtensionAlreadyLoaded:
                print(f"{timestamp()} ⚠️ Cog '{cog_name}' already loaded.")
            except commands.ExtensionNotFound:
                print(f"{timestamp()} ❌ Cog '{cog_name}' not found.")
            except commands.NoEntryPointError:
                print(f"{timestamp()} ❌ Cog '{cog_name}' has no setup function.")
            except Exception as e:
                print(f"{timestamp()} ❌ Failed to load cog '{cog_name}': {e}")
                traceback.print_exc()


# -------------------- ERROR HANDLER --------------------
@bot.event
async def on_command_error(ctx, error):
    with open("error.txt", "a", encoding="utf-8") as f:
        f.write(f"\n{timestamp()} [ERROR] {type(error).__name__}: {error}\n")
        traceback.print_exception(type(error), error, error.__traceback__, file=f)

    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("You're missing a required argument.", delete_after=5)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"That command is on cooldown. Try again in {round(error.retry_after, 1)}s.", delete_after=5)
    else:
        await ctx.send("An unexpected error occurred.", delete_after=5)


# -------------------- ON READY --------------------
@bot.event
async def on_ready():
    await load_cogs()  # Load all cogs automatically
    print(f"{timestamp()} Logged in as {bot.user} ({bot.user.id})")

    activity = discord.Activity(
        type=discord.ActivityType.listening,
        name="Multi-purpose Utility Bot for Gaza Guild."
    )
    await bot.change_presence(activity=activity)

    # Sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"{timestamp()} Synced {len(synced)} slash command(s)")
        for cmd in synced:
            print(f"{timestamp()} - {cmd.name}")
    except Exception as e:
        print(f"{timestamp()} Failed to sync commands: {e}")
        traceback.print_exc()


# -------------------- RUN BOT --------------------
if __name__ == "__main__":
    try:
        bot.run("YOUR_BOT_TOKEN_HERE")
    except Exception as e:
        print(f"{timestamp()} Failed to start bot: {e}")
        traceback.print_exc()

