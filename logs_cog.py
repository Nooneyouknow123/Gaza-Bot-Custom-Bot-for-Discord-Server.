# logs_cog.py
# Advanced Logging Cog (discord.py v2)
# Merged: SQLite persistence + extended events + modern embeds + audit info

import discord
from discord.ext import commands
import aiosqlite
import os
import datetime
import traceback
from typing import Optional

DB_FILE = "logging.db"
VALID_CATEGORIES = ["message", "member", "role", "channel", "emoji", "voice", "mod", "audit"]

# -------------------- DATABASE --------------------

async def init_db():
    conn = await aiosqlite.connect(DB_FILE)
    c = await conn.cursor()
    await c.execute('''
        CREATE TABLE IF NOT EXISTS guild_logs (
            guild_id TEXT PRIMARY KEY,
            message_channel TEXT,
            member_channel TEXT,
            role_channel TEXT,
            channel_channel TEXT,
            emoji_channel TEXT,
            voice_channel TEXT,
            mod_channel TEXT,
            audit_channel TEXT
        )
    ''')
    await conn.commit()
    await conn.close()


async def load_data():
    if not os.path.exists(DB_FILE):
        await init_db()
        return {}
    conn = await aiosqlite.connect(DB_FILE)
    c = await conn.cursor()
    data = {}
    await c.execute('SELECT * FROM guild_logs')
    rows = await c.fetchall()
    for row in rows:
        guild_id = row[0]
        data[guild_id] = {
            "channels": {
                "message": row[1],
                "member": row[2],
                "role": row[3],
                "channel": row[4],
                "emoji": row[5],
                "voice": row[6],
                "mod": row[7],
                "audit": row[8]
            }
        }
    await conn.close()
    return data


async def save_data(data):
    await init_db()
    conn = await aiosqlite.connect(DB_FILE)
    c = await conn.cursor()
    for guild_id, guild_data in data.items():
        channels = guild_data.get("channels", {})
        await c.execute('''
            INSERT OR REPLACE INTO guild_logs 
            (guild_id, message_channel, member_channel, role_channel, channel_channel, emoji_channel, voice_channel, mod_channel, audit_channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            guild_id,
            channels.get("message"),
            channels.get("member"),
            channels.get("role"),
            channels.get("channel"),
            channels.get("emoji"),
            channels.get("voice"),
            channels.get("mod"),
            channels.get("audit")
        ))
    await conn.commit()
    await conn.close()


def ensure_guild(data, guild_id):
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {
            "channels": {cat: None for cat in VALID_CATEGORIES}
        }
    else:
        for cat in VALID_CATEGORIES:
            if cat not in data[gid]["channels"]:
                data[gid]["channels"][cat] = None
    return data[gid]

# -------------------- EMBED HELPERS --------------------

def create_log_embed(title: str, description: str, color: discord.Color = discord.Color.blurple(), icon: Optional[str] = None, author: Optional[discord.abc.User] = None, thumbnail: Optional[str] = None):
    e = discord.Embed(title=(f"{icon} {title}" if icon else title), description=description, color=color, timestamp=datetime.datetime.utcnow())
    footer_text = "🛡️ Server Logs • Advanced Logging System"
    e.set_footer(text=footer_text)
    if author:
        try:
            e.set_author(name=str(author), icon_url=author.display_avatar.url)
        except Exception:
            e.set_author(name=str(author))
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    return e


def format_content(content: Optional[str], max_length: int = 1024) -> str:
    if not content:
        return "*(empty)*"
    content = content.strip()
    if len(content) > max_length:
        return content[:max_length-3] + "..."
    return content


def create_field_section(embed: discord.Embed, title: str, value: str, inline: bool = False):
    if value:
        if len(value) > 1024:
            value = value[:1021] + "..."
        embed.add_field(name=f"📋 {title}", value=value, inline=inline)

# -------------------- LOGS COG --------------------

class LogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data = {}

    async def cog_load(self):
        self.data = await load_data()

    async def save(self):
        try:
            await save_data(self.data)
        except Exception:
            traceback.print_exc()

    def guild_conf(self, guild_id):
        return ensure_guild(self.data, guild_id)

    async def log(self, guild: discord.Guild, category: str, *, embed: discord.Embed = None, file: discord.File = None, content: str = None):
        try:
            g = self.guild_conf(guild.id)
            chan_id = g["channels"].get(category)
            if not chan_id:
                return
            channel = guild.get_channel(int(chan_id))
            if not channel:
                return
            await channel.send(content=content, embed=embed, file=file)
        except Exception:
            # Logging failures should not crash the bot
            traceback.print_exc()

    # ---------------- SETUP COMMANDS ----------------

    @commands.command(name="setlog")
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx, category: str, channel: discord.TextChannel):
        valid = VALID_CATEGORIES
        category_emojis = {
            "message": "💬", "member": "👥", "role": "🎭",
            "channel": "📁", "emoji": "😀", "voice": "🎵", "mod": "🛡️", "audit": "📜"
        }
        category = category.lower()
        if category not in valid:
            embed = create_log_embed(
                "❌ Invalid Category",
                "**Available Categories:**\n" + "\n".join([f"{category_emojis.get(cat, '📝')} **`{cat}`**" for cat in valid]),
                discord.Color.red()
            )
            await ctx.send(embed=embed)
            return
        g = self.guild_conf(ctx.guild.id)
        g["channels"][category] = str(channel.id)
        await self.save()
        embed = create_log_embed(
            "✅ Log Channel Configured",
            f"**{category_emojis.get(category, '📝')} {category.capitalize()} Logs** will now be sent to:\n{channel.mention}",
            discord.Color.green()
        )
        await ctx.send(embed=embed)

    @commands.command(name="logconfig")
    @commands.has_permissions(administrator=True)
    async def log_config(self, ctx):
        g = self.guild_conf(ctx.guild.id)
        category_emojis = {
            "message": "💬", "member": "👥", "role": "🎭",
            "channel": "📁", "emoji": "😀", "voice": "🎵", "mod": "🛡️", "audit": "📜"
        }
        description = ""
        for cat, cid in g["channels"].items():
            status = f"✅ <#{cid}>" if cid else "❌ *(not set)*"
            description += f"{category_emojis.get(cat, '📝')} **{cat.capitalize()}:** {status}\n"
        embed = create_log_embed("⚙️ Logging Configuration", description, discord.Color.blurple())
        embed.add_field(name="📖 Usage", value="Use `!setlog <category> <channel>` to configure logging (command prefix is defined in your main bot).", inline=False)
        await ctx.send(embed=embed)

    # ---------------- MESSAGE LOGS ----------------

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        desc = f"👤 **Author:** {message.author.mention} (`{message.author.id}`)\n📁 **Channel:** {message.channel.mention}\n🆔 **Message ID:** `{message.id}`"
        embed = create_log_embed("🗑️ Message Deleted", desc, discord.Color.orange(), "🗑️")
        if message.content:
            create_field_section(embed, "Content", format_content(message.content))
        if message.attachments:
            urls = "\n".join(a.url for a in message.attachments)
            create_field_section(embed, "Attachments", urls, inline=False)
        await self.log(message.guild, "message", embed=embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        desc = f"👤 **Author:** {before.author.mention} (`{before.author.id}`)\n📁 **Channel:** {before.channel.mention}\n🔗 [Jump to Message]({after.jump_url})"
        embed = create_log_embed("✏️ Message Edited", desc, discord.Color.orange(), "✏️", author=before.author)
        create_field_section(embed, "Before", format_content(before.content))
        create_field_section(embed, "After", format_content(after.content))
        await self.log(before.guild, "message", embed=embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        embed = create_log_embed("🧹 Bulk Message Delete", f"📁 **Channel:** {channel.mention}\n📊 **Messages Deleted:** `{len(messages)}`", discord.Color.orange(), "🧹")
        await self.log(guild, "message", embed=embed)

    # ---------------- REACTION LOGS ----------------

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        msg = reaction.message
        desc = f"👤 **User:** {user.mention} (`{user.id}`)\n😀 **Emoji:** {reaction.emoji}\n📁 **Channel:** {msg.channel.mention}\n🔗 [Jump to Message]({msg.jump_url})"
        embed = create_log_embed("➕ Reaction Added", desc, discord.Color.green(), "➕", author=user)
        await self.log(msg.guild, "message", embed=embed)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        msg = reaction.message
        desc = f"👤 **User:** {user.mention} (`{user.id}`)\n😀 **Emoji:** {reaction.emoji}\n📁 **Channel:** {msg.channel.mention}\n🔗 [Jump to Message]({msg.jump_url})"
        embed = create_log_embed("➖ Reaction Removed", desc, discord.Color.orange(), "➖", author=user)
        await self.log(msg.guild, "message", embed=embed)

    # ---------------- MEMBER LOGS ----------------

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        embed = create_log_embed("👋 Member Joined", f"👤 **Member:** {member.mention} (`{member.id}`)\n👥 **Member Count:** `{member.guild.member_count}`", discord.Color.green(), "👋", author=member, thumbnail=member.display_avatar.url)
        await self.log(member.guild, "member", embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        roles = ", ".join([r.name for r in member.roles if r != member.guild.default_role]) or "(none)"
        desc = f"{member.mention} (`{member.id}`) left the server.\n**Roles:** {roles}"
        embed = create_log_embed("🚪 Member Left", desc, discord.Color.red(), "🚪")
        await self.log(member.guild, "member", embed=embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before == after:
            return
        parts = []
        if before.display_name != after.display_name:
            parts.append(f"**Nickname:** `{before.display_name}` → `{after.display_name}`")
        if before.roles != after.roles:
            added = [r.name for r in after.roles if r not in before.roles]
            removed = [r.name for r in before.roles if r not in after.roles]
            if added:
                parts.append("**Roles Added:** " + ", ".join(added))
            if removed:
                parts.append("**Roles Removed:** " + ", ".join(removed))
        if before.pending != after.pending:
            parts.append("Membership screening state changed.")
        if parts:
            desc = f"{after.mention} (`{after.id}`)\n" + "\n".join(parts)
            embed = create_log_embed("🔄 Member Updated", desc, discord.Color.blurple(), "🔄")
            await self.log(after.guild, "member", embed=embed)

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        desc = f"**User:** {user} (`{user.id}`) was banned."
        try:
            entry = None
            async for e in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                entry = e
                break
            if entry and entry.target.id == user.id:
                desc += f"\n**By:** {entry.user} (`{entry.user.id}`)"
            embed = create_log_embed("🔨 User Banned", desc, discord.Color.dark_red(), "🔨")
        except Exception:
            embed = create_log_embed("🔨 User Banned", desc, discord.Color.dark_red(), "🔨")
        await self.log(guild, "member", embed=embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        desc = f"**User:** {user} (`{user.id}`) was unbanned."
        try:
            entry = None
            async for e in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                entry = e
                break
            if entry and getattr(entry.target, "id", None) == user.id:
                desc += f"\n**By:** {entry.user} (`{entry.user.id}`)"
            embed = create_log_embed("⚪ User Unbanned", desc, discord.Color.green(), "⚪")
        except Exception:
            embed = create_log_embed("⚪ User Unbanned", desc, discord.Color.green(), "⚪")
        await self.log(guild, "member", embed=embed)

    # ---------------- INVITE LOGS ----------------

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        creator = getattr(invite, "inviter", None)
        desc = (f"🔗 **Code:** `{invite.code}`\n"
                f"📁 **Channel:** {invite.channel.mention if invite.channel else 'Unknown'}\n"
                f"👤 **Created by:** {creator.mention if creator else 'Unknown'}\n"
                f"🔢 **Max Uses:** {invite.max_uses or '∞'}\n"
                f"⏰ **Expires (seconds):** {invite.max_age or 'Never'}")
        embed = create_log_embed("🔗 Invite Created", desc, discord.Color.green(), "🔗")
        await self.log(invite.guild, "member", embed=embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        desc = f"🔗 **Code:** `{invite.code}` was deleted."
        embed = create_log_embed("❌ Invite Deleted", desc, discord.Color.red(), "❌")
        await self.log(invite.guild, "member", embed=embed)

    # ---------------- ROLE LOGS ----------------

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        embed = create_log_embed("➕ Role Created", f"**{role.name}** ({role.id}) was created.", discord.Color.blurple(), "➕")
        await self.log(role.guild, "role", embed=embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        desc = f"**{role.name}** ({role.id}) was deleted."
        try:
            entry = None
            async for e in role.guild.audit_logs(limit=3, action=discord.AuditLogAction.role_delete):
                entry = e
                break
            if entry:
                desc += f"\n**By:** {entry.user} (`{entry.user.id}`)"
        except Exception:
            pass
        embed = create_log_embed("🗑️ Role Deleted", desc, discord.Color.blurple(), "🗑️")
        await self.log(role.guild, "role", embed=embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        changes = []
        if before.name != after.name:
            changes.append(f"Name: `{before.name}` → `{after.name}`")
        if before.color != after.color:
            changes.append("Color changed.")
        if before.permissions != after.permissions:
            changes.append("Permissions changed.")
        if changes:
            embed = create_log_embed("🎨 Role Updated", f"**{after.name}** ({after.id})\n" + "\n".join(changes), discord.Color.blurple(), "🎨")
            await self.log(after.guild, "role", embed=embed)

    # ---------------- CHANNEL LOGS ----------------

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        embed = create_log_embed("📢 Channel Created", f"{channel.mention} ({channel.id}) was created.", discord.Color.teal(), "📢")
        await self.log(channel.guild, "channel", embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        embed = create_log_embed("🗑️ Channel Deleted", f"#{channel.name} ({channel.id}) was deleted.", discord.Color.teal(), "🗑️")
        await self.log(channel.guild, "channel", embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        embed = create_log_embed("⚙️ Channel Updated", f"{after.mention} permissions or settings were changed.", discord.Color.teal(), "⚙️")
        await self.log(after.guild, "channel", embed=embed)

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel: discord.abc.GuildChannel, last_pin: Optional[datetime.datetime]):
        ts = last_pin.isoformat() if last_pin else "Unknown"
        embed = create_log_embed("📌 Pins Updated", f"Pins updated in {channel.mention}. Last pin: {ts}", discord.Color.dark_gray(), "📌")
        await self.log(channel.guild, "message", embed=embed)

    # ---------------- EMOJI LOGS ----------------

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        before_names = {e.name for e in before}
        after_names = {e.name for e in after}
        if len(before) < len(after):
            embed = create_log_embed("😀 Emoji Created", "A new emoji was added.", discord.Color.gold(), "😀")
        elif len(before) > len(after):
            embed = create_log_embed("❌ Emoji Deleted", "An emoji was removed.", discord.Color.gold(), "❌")
        elif before_names != after_names:
            embed = create_log_embed("✏️ Emoji Renamed", "An emoji name was changed.", discord.Color.gold(), "✏️")
        else:
            return
        await self.log(guild, "emoji", embed=embed)

    # ---------------- VOICE LOGS ----------------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if before.channel is None and after.channel:
            embed = create_log_embed("🎵 Voice Join", f"{member.mention} joined {after.channel.mention}", discord.Color.purple(), "🎧", author=member)
        elif after.channel is None and before.channel:
            embed = create_log_embed("🎵 Voice Leave", f"{member.mention} left {before.channel.mention}", discord.Color.purple(), "🎤", author=member)
        elif before.channel and after.channel and before.channel != after.channel:
            embed = create_log_embed("🎵 Voice Move", f"{member.mention} moved from {before.channel.mention} → {after.channel.mention}", discord.Color.purple(), "🎙️", author=member)
        else:
            return
        await self.log(member.guild, "voice", embed=embed)

    # ---------------- WEBHOOKS / INTEGRATIONS / AUDIT ----------------

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        embed = create_log_embed("🔌 Webhooks Updated", f"Webhooks were updated in {channel.mention}", discord.Color.gold(), "🔌")
        await self.log(channel.guild, "audit", embed=embed)

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild):
        embed = create_log_embed("🔗 Integrations Updated", f"Integrations were updated in **{guild.name}**", discord.Color.gold(), "🔗")
        await self.log(guild, "audit", embed=embed)

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        parts = []
        if before.name != after.name:
            parts.append(f"Name: `{before.name}` → `{after.name}`")
        if getattr(before, 'vanity_url_code', None) != getattr(after, 'vanity_url_code', None):
            parts.append("Vanity URL changed.")
        if parts:
            embed = create_log_embed("🏷️ Server Updated", f"Updates for {after.name}\n" + "\n".join(parts), discord.Color.blurple(), "🏷️")
            await self.log(after, "audit", embed=embed)

    # ---------------- FALLBACK / ERROR LOGGING ----------------

    @commands.Cog.listener()
    async def on_error(self, event_method, /, *args, **kwargs):
        print(f"[LogsCog] Internal error in {event_method}:")
        traceback.print_exc()

    async def cog_unload(self):
        try:
            await save_data(self.data)
        except Exception:
            traceback.print_exc()

async def setup(bot: commands.Bot):
    await init_db()
    await bot.add_cog(LogsCog(bot))
