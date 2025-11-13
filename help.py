import discord
from discord.ext import commands
from discord.ui import View, Select

# ---------------- ANIMATED ICONS + BANNER ----------------
ICONS = {
    "Overview": "https://cdn.discordapp.com/emojis/1169859279274027058.gif?size=96",
    "Moderation": "https://cdn.discordapp.com/emojis/1219984983453052988.gif?size=96",
    "Jail / Appeals": "https://cdn.discordapp.com/emojis/1222193893752088636.gif?size=96",
    "Logs": "https://cdn.discordapp.com/emojis/1139274231092348958.gif?size=96",
    "Utility": "https://cdn.discordapp.com/emojis/1222194388015618110.gif?size=96",
    "All Commands": "https://cdn.discordapp.com/emojis/1219984860338464808.gif?size=96"
}

BANNER = "https://cdn.discordapp.com/banners/1222193854027610183/8ac2b66bdcfdf34d90efc893a3926a19.gif?size=1024"

# ---------------- HELP EMBED GENERATOR ----------------
def make_help_embed(category: str) -> discord.Embed:
    bl = discord.Color.blurple()

    def base(title, desc):
        embed = discord.Embed(title=title, description=desc, color=bl)
        embed.set_image(url=BANNER)
        embed.set_thumbnail(url=ICONS.get(category, list(ICONS.values())[0]))
        embed.set_footer(text="Use the dropdown to switch categories.")
        return embed

    # ---------------- OVERVIEW ----------------
    if category == "Overview":
        embed = base(
            "📘 Bot Overview",
            "This bot provides moderation, jail/appeals, and logging.\n"
            "Prefix: `.` (dot). Example: `.jail @user reason`"
        )
        embed.add_field(
            name="Quick Setup",
            value=(
                "`·` `.setlog <category> #channel`\n"
                "`·` `.setstaffrole @role`\n"
                "`·` `.jailrole <role>`\n"
                "`·` `.setupjail`"
            ),
            inline=False
        )
        return embed

    # ---------------- MODERATION ----------------
    if category == "Moderation":
        embed = base("🛠️ Moderation Commands", "These commands require staff permissions.")
        embed.add_field(name="Warnings", value="`.warn`, `.warnlist`, `.removewarn`, `.clearwarns`", inline=False)
        embed.add_field(name="Timeouts & Notes", value="`.mute`, `.unmute`, `.note`", inline=False)
        embed.add_field(name="Punishments", value="`.jail`, `.unjail`, `.ban`, `.unban`, `.kick`", inline=False)
        return embed

    # ---------------- JAIL / APPEALS ----------------
    if category == "Jail / Appeals":
        embed = base("🔒 Jail / Appeals System", "Handles jail role and ticket-based appeals.")
        embed.add_field(name="Setup", value="`.setupjail`, `.setjailadmins @role`", inline=False)
        embed.add_field(name="Resolve Appeals", value="`.approve`, `.deny <reason>`", inline=False)
        return embed

    # ---------------- LOGS ----------------
    if category == "Logs":
        embed = base("📜 Logging System", "Send different log types to different channels.")
        embed.add_field(name="Commands", value="`.setlog <category> #channel`, `.logconfig`", inline=False)
        embed.add_field(name="Recommended Channels", value="mod-logs, message-logs, member-logs", inline=False)
        return embed

    # ---------------- UTILITY ----------------
    if category == "Utility":
        embed = base("⚙️ Utility Commands", "Owner / debug utilities.")
        embed.add_field(name="Commands", value="`.reload`, `.list_commands`, `.list_cog_commands`", inline=False)
        return embed

    # ---------------- ALL COMMANDS ----------------
    if category == "All Commands":
        embed = base("📋 Full Command List", "A categorized overview of all available bot commands.")

        # 🧩 Setup Commands
        embed.add_field(
            name="⚙️ Setup Commands",
            value=(
                "`setlog` — Set the log channel for moderation actions.\n"
                "`logconfig` — Configure what actions are logged.\n"
                "`setstaffrole` — Assign or change the staff role.\n"
                "`jailrole` — Set the role to use for jailed users.\n"
                "`setupjail` — Create the jail system automatically.\n"
                "`setjailadmins` — Allow certain roles/users to jail members."
            ),
            inline=False
        )

        # 🔨 Moderation Commands
        embed.add_field(
            name="🔨 Moderation Commands",
            value=(
                "`jail` — Restrict a user with the jail role.\n"
                "`unjail` — Release a user from jail.\n"
                "`warn` — Warn a user for breaking rules.\n"
                "`warnlist` — Show all warnings for a user.\n"
                "`removewarn` — Remove a specific warning.\n"
                "`clearwarns` — Clear all warnings for a user.\n"
                "`note` — Add a private staff note about a user.\n"
                "`mute` — Temporarily prevent a user from chatting.\n"
                "`unmute` — Unmute a previously muted user.\n"
                "`ban` — Ban a user from the server.\n"
                "`unban` — Unban a previously banned user.\n"
                "`kick` — Kick a user from the server."
            ),
            inline=False
        )

        # 📝 Application System
        embed.add_field(
            name="📝 Application System",
            value="`approve` — Approve a pending application.\n`deny` — Deny an application with a reason.",
            inline=False
        )

        # 🎉 Fun Commands
        embed.add_field(
            name="🎉 Fun Commands",
            value="`fakeban` — Pretend to ban a user (harmless prank).",
            inline=False
        )

        # 💬 Slash Commands
        embed.add_field(
            name="💬 Slash Commands",
            value="`/fakeban` — Simulates banning a user with options like prank, silent, and DM.",
            inline=False
        )

        embed.set_footer(text="Use commands responsibly • Type /help <command> for details.")
        return embed

    # Default fallback
    return base("Help", "No help available.")

# ---------------- MENU DROPDOWN ----------------
class HelpSelect(Select):
    def __init__(self, requester_id: int):
        options = [
            discord.SelectOption(label="Overview", emoji="📘"),
            discord.SelectOption(label="Moderation", emoji="🛠️"),
            discord.SelectOption(label="Jail / Appeals", emoji="🔒"),
            discord.SelectOption(label="Logs", emoji="📜"),
            discord.SelectOption(label="Utility", emoji="⚙️"),
            discord.SelectOption(label="All Commands", emoji="📋"),
        ]
        super().__init__(placeholder="Choose a help category...", min_values=1, max_values=1, options=options)
        self.requester_id = requester_id

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message("This help menu isn't for you.", ephemeral=True)
            return

        embed = make_help_embed(self.values[0])
        await interaction.response.edit_message(embed=embed, view=self.view)

class HelpView(View):
    def __init__(self, requester_id: int):
        super().__init__(timeout=300)
        self.add_item(HelpSelect(requester_id))

# ---------------- COG ----------------
class HelpCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(name="help")
    async def help_command(self, ctx):
        embed = make_help_embed("Overview")
        view = HelpView(ctx.author.id)
        await ctx.send(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(HelpCog(bot))
