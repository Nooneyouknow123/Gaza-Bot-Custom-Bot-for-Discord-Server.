# file: cogs/fakeban_slash.py
import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import get
import asyncio
from datetime import datetime

class FakeBanSlash(commands.Cog):
    """A fun slash-command version of the fake ban command (safe simulation)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="fakeban", description="Simulate banning a user (for fun/testing). No real ban occurs.")
    @app_commands.describe(
        user="The user to (fake) ban",
        reason="Reason for the fake ban (optional)",
        prank="Show a countdown prank before the message",
        silent="Post only to mod-log, not in public channel",
        dm="Try to DM the fake ban message to the user"
    )
    @app_commands.checks.has_permissions(ban_members=True)
    async def fakeban(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        reason: str = "No reason provided",
        prank: bool = False,
        silent: bool = False,
        dm: bool = False,
    ):
        await interaction.response.defer(thinking=True, ephemeral=silent)

        timestamp = datetime.utcnow()

        # Optional prank countdown
        if prank and not silent:
            try:
                countdown = await interaction.followup.send(f"Initiating fake ban sequence for **{user}**...\n3️⃣")
                await asyncio.sleep(0.8)
                await countdown.edit(content=f"Initiating fake ban sequence for **{user}**...\n2️⃣")
                await asyncio.sleep(0.8)
                await countdown.edit(content=f"Initiating fake ban sequence for **{user}**...\n1️⃣")
                await asyncio.sleep(0.6)
                await countdown.delete()
            except Exception:
                pass

        # Create the main fake ban embed
        embed = discord.Embed(
            title="User Banned (simulated)",
            description=f"**{user}** has been *fake banned* from **{interaction.guild.name}**.",
            color=discord.Color.red(),
            timestamp=timestamp,
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="User", value=f"{user} ({user.id})", inline=False)
        embed.add_field(name="Moderator", value=f"{interaction.user} ({interaction.user.id})", inline=False)
        embed.add_field(name="Reason", value=reason, inline=False)
        embed.add_field(name="Note", value="⚠️ This is a **simulated** ban — no action was taken.", inline=False)
        embed.set_footer(text=f"Fake ban • {interaction.guild.name}")

        # Try to DM the user (if requested)
        dm_status = "No DM attempted."
        if dm:
            try:
                dm_embed = discord.Embed(
                    title=f"You were banned from {interaction.guild.name} (simulated)",
                    description=(
                        f"Hey {user.display_name}, this is a **fake ban** message for fun/testing.\n\n"
                        f"**Moderator:** {interaction.user}\n"
                        f"**Reason:** {reason}\n\n"
                        "You’re not actually banned — this was just for laughs 😄"
                    ),
                    color=discord.Color.orange(),
                    timestamp=timestamp,
                )
                await user.send(embed=dm_embed)
                dm_status = "DM sent successfully."
            except discord.Forbidden:
                dm_status = "Could not DM user (forbidden)."
            except discord.HTTPException:
                dm_status = "Could not DM user (HTTP error)."

        # Log channel lookup
        log_channel = get(interaction.guild.text_channels, name="mod-log") or get(
            interaction.guild.text_channels, name="mod-logs"
        )

        # Send the fake ban embed
        if not silent:
            await interaction.followup.send(embed=embed)

        # Post to mod-log channel if found
        if log_channel:
            log_embed = embed.copy()
            log_embed.color = discord.Color.dark_grey()
            log_embed.add_field(name="Simulated?", value="Yes — no real ban occurred.", inline=False)
            log_embed.add_field(name="DM Status", value=dm_status, inline=False)
            try:
                await log_channel.send(embed=log_embed)
            except Exception:
                pass

    @fakeban.error
    async def on_fakeban_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("You need the **Ban Members** permission to use this command.", ephemeral=True)
        else:
            print(f"[fakeban_slash] Error: {error}")
            await interaction.response.send_message("An unexpected error occurred.", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(FakeBanSlash(bot))
