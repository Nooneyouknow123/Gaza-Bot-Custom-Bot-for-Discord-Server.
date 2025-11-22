import discord

from discord.ext import commands

from discord import app_commands

# Your developer ID

DEVELOPER_IDS = {

    951863963132506232

}

class ServerManager(commands.Cog):

    def __init__(self, bot: commands.Bot):

        self.bot = bot

    # Developer-only check

    async def dev_only(self, interaction: discord.Interaction):

        return interaction.user.id in DEVELOPER_IDS

    # ───────────────────────────────────────

    # LIST ALL SERVERS (DEV ONLY)

    # ───────────────────────────────────────

    @app_commands.command(

        name="servers",

        description="List all servers the bot is in (Developer Only)."

    )

    async def servers(self, interaction: discord.Interaction):

        if not await self.dev_only(interaction):

            return await interaction.response.send_message(

                "Developer-only command.", ephemeral=True

            )

        guilds = self.bot.guilds

        msg = "**Servers I'm in:**\n"

        for g in guilds:

            owner = g.owner

            owner_info = f"{owner} (`{owner.id}`)" if owner else "Unknown"

            msg += f"- **{g.name}** (`{g.id}`) | Owner: {owner_info}\n"

        await interaction.response.send_message(msg, ephemeral=True)

    # ───────────────────────────────────────

    # CREATE INVITE USING SERVER ID (DEV ONLY)

    # ───────────────────────────────────────

    @app_commands.command(

        name="invite_to",

        description="Create an invite for a server using its ID (Developer Only)."

    )

    @app_commands.describe(server_id="The ID of the server")

    async def invite_to(self, interaction: discord.Interaction, server_id: str):

        if not await self.dev_only(interaction):

            return await interaction.response.send_message(

                "Developer-only command.", ephemeral=True

            )

        # find guild by ID

        guild = self.bot.get_guild(int(server_id))

        if guild is None:

            return await interaction.response.send_message(

                "I'm not in a server with that ID.", ephemeral=True

            )

        owner = guild.owner

        owner_info = f"{owner} (`{owner.id}`)" if owner else "Unknown"

        # find a channel where the bot can create an invite

        channel = None

        for ch in guild.text_channels:

            perms = ch.permissions_for(guild.me)

            if perms.create_instant_invite:

                channel = ch

                break

        if channel is None:

            return await interaction.response.send_message(

                "I cannot create an invite in that server (missing permissions).",

                ephemeral=True

            )

        # create invite

        invite = await channel.create_invite(

            max_age=0,

            max_uses=0,

            reason=f"Invite created by developer {interaction.user}"

        )

        await interaction.response.send_message(

            f"Invite for **{guild.name}** (`{guild.id}`)\n"

            f"Owner: {owner_info}\n"

            f"{invite.url}",

            ephemeral=True

        )

async def setup(bot):

    await bot.add_cog(ServerManager(bot))

