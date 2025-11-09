import discord
from discord.ext import commands
import os
print("🚀 Datei wurde gestartet")

# -------------------- INTENTS --------------------
intents = discord.Intents.default()
intents.messages = True
intents.message_content = True  # Required for reading message content
intents.guilds = True

# -------------------- BOT INSTANCE --------------------
bot = commands.Bot(command_prefix=".", intents=intents)

# -------------------- COMMANDS --------------------
@bot.command()
async def list_commands(ctx):
    commands_list = [command.name for command in bot.commands]
    await ctx.send(f"Available commands: {', '.join(commands_list)}")

@bot.command()
async def list_cog_commands(ctx):
    for cog_name, cog in bot.cogs.items():
        commands_list = [command.name for command in cog.get_commands()]
        await ctx.send(f"Commands in {cog_name}: {', '.join(commands_list)}")

@bot.command()
@commands.is_owner()  # Only bot owner can reload cogs
async def reload(ctx, cog: str = None):
    """Reloads all cogs or a specific one."""
    cogs_path = "./cogs"

    if cog:
        # Reload a specific cog
        cog_name = f"cogs.{cog}"
        try:
            await bot.reload_extension(cog_name)
            await ctx.send(f"✅ Reloaded `{cog}` successfully!")
        except Exception as e:
            await ctx.send(f"❌ Failed to reload `{cog}`: `{e}`")
    else:
        # Reload all cogs
        reloaded = []
        failed = []
        for filename in os.listdir(cogs_path):
            if filename.endswith(".py"):
                cog_name = f"cogs.{filename[:-3]}"
                try:
                    await bot.reload_extension(cog_name)
                    reloaded.append(filename[:-3])
                except Exception as e:
                    failed.append((filename[:-3], str(e)))

        await ctx.send(
            f"✅ Reloaded: {', '.join(reloaded)}\n"
            f"❌ Failed: {', '.join(f'{cog} ({err})' for cog, err in failed) if failed else 'None'}"
        )

# -------------------- GLOBAL ERROR HANDLER --------------------
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingPermissions):
        await ctx.send("You don't have permission to use this command.", delete_after=5)
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("You're missing a required argument for this command.", delete_after=5)
    elif isinstance(error, commands.CommandOnCooldown):
        await ctx.send(f"That command is on cooldown. Try again in {round(error.retry_after, 1)} seconds.", delete_after=5)
    else:
        print(f"An error occurred: {error}")

# -------------------- COG LOADING --------------------
async def load_cogs():
    # Explicit load order for dependencies
    cog_order = ["leveling_system", "economy", "shop"]  # filenames without .py

    for cog_name in cog_order:
        try:
            await bot.load_extension(f"cogs.{cog_name}")  # ✅ await coroutine
            print(f"Loaded cog: {cog_name}")
        except Exception as e:
            print(f"Failed to load cog {cog_name}: {e}")

    # Load any other remaining cogs automatically
    for filename in os.listdir("./cogs"):
        if filename.endswith(".py"):
            name = filename[:-3].lower()
            if name in cog_order:
                continue  # already loaded
            try:
                await bot.load_extension(f"cogs.{name}")  # ✅ await coroutine
                print(f"Loaded cog: {name}")
            except Exception as e:
                print(f"Failed to load cog {name}: {e}")

# -------------------- ON READY --------------------
@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")
    await load_cogs()

# -------------------- RUN BOT --------------------
bot.run("MTMwNTMxNDkzNDQwMTQwNDk4OQ.G7Znh3.C3dFh9zJqKCAJGOqOtW472fBGy664u0mMCjVSg")  # Replace with your bot token
