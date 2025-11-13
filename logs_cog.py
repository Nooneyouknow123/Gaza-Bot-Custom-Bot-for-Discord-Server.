# logs_cog.py
# Advanced Logging Cog (discord.py v2)
# Use aiosqlite, embeds, audit.logs, and various event listeners to log server events.

import discord
from discord.ext import commands
import aiosqlite
import os
import datetime
import traceback
from typing import Optional, Any, Dict

# ===========================================================================================
#                                  CONFIGURATION & CONSTANTS
# ===========================================================================================

DB_FILE = "logging.db"
VALID_CATEGORIES = ["message", "member", "role", "channel", "emoji", "voice", "mod", "audit"]

# ===========================================================================================
#                                  DATABASE OPERATIONS
# ===========================================================================================

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

async def load_data() -> Dict[str, Any]:
    if not os.path.exists(DB_FILE):
        await init_db()
        return {}
    
    conn = await aiosqlite.connect(DB_FILE)
    c = await conn.cursor()
    data: Dict[str, Any] = {}
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

async def save_data(data: Dict[str, Any]):
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

# ===========================================================================================
#                                  UTILITY FUNCTIONS
# ===========================================================================================

def ensure_guild(data: Dict[str, Any], guild_id) -> Dict[str, Any]:
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {"channels": {cat: None for cat in VALID_CATEGORIES}}
    else:
        for cat in VALID_CATEGORIES:
            if cat not in data[gid]["channels"]:
                data[gid]["channels"][cat] = None
    return data[gid]

def create_log_embed(title: str,
                     description: str,
                     color: discord.Color = discord.Color.blurple(),
                     icon: Optional[str] = None,
                     author: Optional[discord.User] = None,
                     thumbnail: Optional[str] = None) -> discord.Embed:
    e = discord.Embed(
        title=(f"{icon} {title}" if icon else title),
        description=description,
        color=color,
        timestamp=datetime.datetime.utcnow()
    )
    footer_text = "🛡️ Server Logs • Advanced Logging System"
    e.set_footer(text=footer_text)
    if author:
        try:
            e.set_author(name=str(author), icon_url=author.display_avatar.url)
        except Exception:
            try:
                e.set_author(name=str(author))
            except Exception:
                pass
    if thumbnail:
        try:
            e.set_thumbnail(url=thumbnail)
        except Exception:
            pass
    return e

def format_content(content: Optional[str], max_length: int = 1024) -> str:
    if not content:
        return "*(empty)*"
    content = content.strip()
    if len(content) > max_length:
        return content[:max_length - 3] + "..."
    return content

def create_field_section(embed: discord.Embed, title: str, value: str, inline: bool = False):
    if value:
        if len(value) > 1024:
            value = value[:1021] + "..."
        embed.add_field(name=f"📋 {title}", value=value, inline=inline)

# ===========================================================================================
#                                  MAIN COG CLASS
# ===========================================================================================

class LogsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.data: Dict[str, Any] = {}

    async def cog_load(self):
        try:
            self.data = await load_data()
            print("[LogsCog] Loaded logging configuration from DB.")
        except Exception:
            print("[LogsCog] Failed to load DB on cog_load.")
            traceback.print_exc()

    async def save(self):
        try:
            await save_data(self.data)
        except Exception:
            print("[LogsCog] Error saving DB:")
            traceback.print_exc()

    def guild_conf(self, guild_id):
        return ensure_guild(self.data, guild_id)

    async def log(self, guild: discord.Guild, category: str, *, embed: Optional[discord.Embed] = None, file: Optional[discord.File] = None, content: Optional[str] = None):
        try:
            g = self.guild_conf(guild.id)
            chan_id = g["channels"].get(category)
            if not chan_id:
                return
            try:
                ch_id_int = int(chan_id)
            except Exception:
                return
            channel = guild.get_channel(ch_id_int)
            if not channel:
                g["channels"][category] = None
                await self.save()
                return
            await channel.send(content=content, embed=embed, file=file)
        except Exception:
            print("[LogsCog] Exception while sending a log message:")
            traceback.print_exc()

# ===========================================================================================
#                                  COMMANDS
# ===========================================================================================

    # ------------------------------------ Set Log ----------------------------------------------
    @commands.command(name="setlog")
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx: commands.Context, category: str, channel: discord.TextChannel):
        try:
            if ctx.guild is None:
                await ctx.send("This command can only be used in a server.")
                return
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
            me = ctx.guild.me
            if me:
                perms = channel.permissions_for(me)
                if not perms.send_messages or not perms.embed_links:
                    await ctx.send(f"I don't have enough permissions in {channel.mention} (required: Send Messages, Embed Links).")
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
            print(f"[LogsCog] Set {category} logging to {channel.id} for guild {ctx.guild.id}")
        except Exception as e:
            print("[LogsCog] Exception in set_log_channel:")
            traceback.print_exc()
            tb = "".join(traceback.format_exception_only(type(e), e))[:1000]
            embed = create_log_embed("❌ Error setting log channel", f"Error: `{tb}`", discord.Color.red())
            await ctx.send(embed=embed)

    # -------------------------------------- Log Config --------------------------------------------
    @commands.command(name="logconfig")
    @commands.has_permissions(administrator=True)
    async def log_config(self, ctx: commands.Context):
        if ctx.guild is None:
            await ctx.send("Only usable in server.")
            return
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
        embed.add_field(name="📖 Usage", value="Use `!setlog <category> <channel>` to configure logging.", inline=False)
        await ctx.send(embed=embed)

# ===========================================================================================
#                                  MESSAGE EVENT LISTENERS
# ===========================================================================================

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        try:
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
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        try:
            if not before.guild or before.author.bot:
                return
            if before.content == after.content:
                return
            desc = f"👤 **Author:** {before.author.mention} (`{before.author.id}`)\n📁 **Channel:** {before.channel.mention}\n🔗 [Jump to Message]({after.jump_url})"
            embed = create_log_embed("✏️ Message Edited", desc, discord.Color.orange(), "✏️", author=before.author)
            create_field_section(embed, "Before", format_content(before.content))
            create_field_section(embed, "After", format_content(after.content))
            await self.log(before.guild, "message", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        try:
            if not messages:
                return
            guild = messages[0].guild
            channel = messages[0].channel
            embed = create_log_embed("🧹 Bulk Message Delete", f"📁 **Channel:** {channel.mention}\n📊 **Messages Deleted:** `{len(messages)}`", discord.Color.orange(), "🧹")
            await self.log(guild, "message", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        try:
            if user.bot or not getattr(reaction, "message", None) or not reaction.message.guild:
                return
            msg = reaction.message
            desc = f"👤 **User:** {user.mention} (`{user.id}`)\n😀 **Emoji:** {reaction.emoji}\n📁 **Channel:** {msg.channel.mention}\n🔗 [Jump to Message]({msg.jump_url})"
            embed = create_log_embed("➕ Reaction Added", desc, discord.Color.green(), "➕", author=user)
            await self.log(msg.guild, "message", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        try:
            if user.bot or not getattr(reaction, "message", None) or not reaction.message.guild:
                return
            msg = reaction.message
            desc = f"👤 **User:** {user.mention} (`{user.id}`)\n😀 **Emoji:** {reaction.emoji}\n📁 **Channel:** {msg.channel.mention}\n🔗 [Jump to Message]({msg.jump_url})"
            embed = create_log_embed("➖ Reaction Removed", desc, discord.Color.orange(), "➖", author=user)
            await self.log(msg.guild, "message", embed=embed)
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  MEMBER EVENT LISTENERS
# ===========================================================================================

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        try:
            embed = create_log_embed("👋 Member Joined", f"👤 **Member:** {member.mention} (`{member.id}`)\n👥 **Member Count:** `{member.guild.member_count}`", discord.Color.green(), "👋", author=member, thumbnail=member.display_avatar.url if member.display_avatar else None)
            await self.log(member.guild, "member", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            roles = ", ".join([r.name for r in member.roles if r != member.guild.default_role]) or "(none)"
            desc = f"{member.mention} (`{member.id}`) left the server.\n**Roles:** {roles}"
            embed = create_log_embed("🚪 Member Left", desc, discord.Color.red(), "🚪")
            await self.log(member.guild, "member", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
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
            if getattr(before, "pending", None) != getattr(after, "pending", None):
                parts.append("Membership screening state changed.")
            if parts:
                desc = f"{after.mention} (`{after.id}`)\n" + "\n".join(parts)
                embed = create_log_embed("🔄 Member Updated", desc, discord.Color.blurple(), "🔄")
                await self.log(after.guild, "member", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_ban(self, guild: discord.Guild, user: discord.User):
        try:
            desc = f"**User:** {user} (`{user.id}`) was banned."
            entry = None
            try:
                async for e in guild.audit_logs(limit=5, action=discord.AuditLogAction.ban):
                    entry = e
                    break
                if entry and getattr(entry.target, "id", None) == user.id:
                    desc += f"\n**By:** {entry.user} (`{entry.user.id}`)"
            except Exception:
                pass
            embed = create_log_embed("🔨 User Banned", desc, discord.Color.dark_red(), "🔨")
            await self.log(guild, "member", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_unban(self, guild: discord.Guild, user: discord.User):
        try:
            desc = f"**User:** {user} (`{user.id}`) was unbanned."
            entry = None
            try:
                async for e in guild.audit_logs(limit=5, action=discord.AuditLogAction.unban):
                    entry = e
                    break
                if entry and getattr(entry.target, "id", None) == user.id:
                    desc += f"\n**By:** {entry.user} (`{entry.user.id}`)"
            except Exception:
                pass
            embed = create_log_embed("⚪ User Unbanned", desc, discord.Color.green(), "⚪")
            await self.log(guild, "member", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_invite_create(self, invite: discord.Invite):
        try:
            creator = getattr(invite, "inviter", None)
            desc = (f"🔗 **Code:** `{invite.code}`\n"
                    f"📁 **Channel:** {invite.channel.mention if invite.channel else 'Unknown'}\n"
                    f"👤 **Created by:** {creator.mention if creator else 'Unknown'}\n"
                    f"🔢 **Max Uses:** {invite.max_uses or '∞'}\n"
                    f"⏰ **Expires (seconds):** {invite.max_age or 'Never'}")
            embed = create_log_embed("🔗 Invite Created", desc, discord.Color.green(), "🔗")
            await self.log(invite.guild, "member", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_invite_delete(self, invite: discord.Invite):
        try:
            desc = f"🔗 **Code:** `{invite.code}` was deleted."
            embed = create_log_embed("❌ Invite Deleted", desc, discord.Color.red(), "❌")
            await self.log(invite.guild, "member", embed=embed)
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  ROLE EVENT LISTENERS
# ===========================================================================================

    @commands.Cog.listener()
    async def on_guild_role_create(self, role: discord.Role):
        try:
            embed = create_log_embed("➕ Role Created", f"**{role.name}** ({role.id}) was created.", discord.Color.blurple(), "➕")
            await self.log(role.guild, "role", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role: discord.Role):
        try:
            desc = f"**{role.name}** ({role.id}) was deleted."
            entry = None
            try:
                async for e in role.guild.audit_logs(limit=3, action=discord.AuditLogAction.role_delete):
                    entry = e
                    break
                if entry:
                    desc += f"\n**By:** {entry.user} (`{entry.user.id}`)"
            except Exception:
                pass
            embed = create_log_embed("🗑️ Role Deleted", desc, discord.Color.blurple(), "🗑️")
            await self.log(role.guild, "role", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_role_update(self, before: discord.Role, after: discord.Role):
        try:
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
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  CHANNEL EVENT LISTENERS
# ===========================================================================================

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel: discord.abc.GuildChannel):
        try:
            embed = create_log_embed("📢 Channel Created", f"{channel.mention} ({channel.id}) was created.", discord.Color.teal(), "📢")
            await self.log(channel.guild, "channel", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel: discord.abc.GuildChannel):
        try:
            embed = create_log_embed("🗑️ Channel Deleted", f"#{channel.name} ({channel.id}) was deleted.", discord.Color.teal(), "🗑️")
            await self.log(channel.guild, "channel", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before: discord.abc.GuildChannel, after: discord.abc.GuildChannel):
        try:
            embed = create_log_embed("⚙️ Channel Updated", f"{after.mention} permissions or settings were changed.", discord.Color.teal(), "⚙️")
            await self.log(after.guild, "channel", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_channel_pins_update(self, channel: discord.abc.GuildChannel, last_pin: Optional[datetime.datetime]):
        try:
            ts = last_pin.isoformat() if last_pin else "Unknown"
            embed = create_log_embed("📌 Pins Updated", f"Pins updated in {channel.mention}. Last pin: {ts}", discord.Color.dark_gray(), "📌")
            await self.log(channel.guild, "message", embed=embed)
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  EMOJI EVENT LISTENERS
# ===========================================================================================

    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild: discord.Guild, before, after):
        try:
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
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  VOICE EVENT LISTENERS
# ===========================================================================================

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        try:
            if before.channel is None and after.channel:
                embed = create_log_embed("🎵 Voice Join", f"{member.mention} joined {after.channel.mention}", discord.Color.purple(), "🎧", author=member)
            elif after.channel is None and before.channel:
                embed = create_log_embed("🎵 Voice Leave", f"{member.mention} left {before.channel.mention}", discord.Color.purple(), "🎤", author=member)
            elif before.channel and after.channel and before.channel != after.channel:
                embed = create_log_embed("🎵 Voice Move", f"{member.mention} moved from {before.channel.mention} → {after.channel.mention}", discord.Color.purple(), "🎙️", author=member)
            else:
                return
            await self.log(member.guild, "voice", embed=embed)
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  AUDIT EVENT LISTENERS
# ===========================================================================================

    @commands.Cog.listener()
    async def on_webhooks_update(self, channel: discord.abc.GuildChannel):
        try:
            embed = create_log_embed("🔌 Webhooks Updated", f"Webhooks were updated in {channel.mention}", discord.Color.gold(), "🔌")
            await self.log(channel.guild, "audit", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_integrations_update(self, guild: discord.Guild):
        try:
            embed = create_log_embed("🔗 Integrations Updated", f"Integrations were updated in **{guild.name}**", discord.Color.gold(), "🔗")
            await self.log(guild, "audit", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        try:
            parts = []
            if before.name != after.name:
                parts.append(f"Name: `{before.name}` → `{after.name}`")
            if getattr(before, 'vanity_url_code', None) != getattr(after, 'vanity_url_code', None):
                parts.append("Vanity URL changed.")
            if parts:
                embed = create_log_embed("🏷️ Server Updated", f"Updates for {after.name}\n" + "\n".join(parts), discord.Color.blurple(), "🏷️")
                await self.log(after, "audit", embed=embed)
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  MODERATION EVENT LISTENERS
# ===========================================================================================



# ===========================================================================================
#                                  GAZA BOT INTEGRATION
# ===========================================================================================

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        try:
            if not message.guild or message.author.bot:
                return
            if "gaza" in message.author.name.lower() or "gaza" in getattr(message.author, "display_name", "").lower():
                content = message.content.lower()
                if "warn" in content and "reason" in content:
                    await self._log_gaza_mod_action(message, "warn")
                elif "jail" in content or "mute" in content:
                    await self._log_gaza_mod_action(message, "jail")
                elif "kick" in content:
                    await self._log_gaza_mod_action(message, "kick")
                elif "ban" in content:
                    await self._log_gaza_mod_action(message, "ban")
        except Exception:
            traceback.print_exc()

    async def _log_gaza_mod_action(self, message: discord.Message, action_type: str):
        try:
            content = message.content
            embeds = message.embeds
            if embeds:
                for embed in embeds:
                    if embed.description or embed.fields:
                        description = embed.description or ""
                        target_user = None
                        moderator = message.author
                        reason = "No reason provided"
                        if message.mentions:
                            target_user = message.mentions[0]
                        for field in embed.fields:
                            if "reason" in field.name.lower():
                                reason = field.value
                            elif "user" in field.name.lower() and not target_user:
                                pass
                        if target_user:
                            action_icons = {
                                "warn": "⚠️",
                                "jail": "🔒", 
                                "kick": "👢",
                                "ban": "🔨",
                                "mute": "🔇"
                            }
                            action_titles = {
                                "warn": "User Warned",
                                "jail": "User Jailed", 
                                "kick": "User Kicked",
                                "ban": "User Banned",
                                "mute": "User Muted"
                            }
                            action_colors = {
                                "warn": discord.Color.gold(),
                                "jail": discord.Color.dark_gray(),
                                "kick": discord.Color.orange(),
                                "ban": discord.Color.dark_red(),
                                "mute": discord.Color.dark_gray()
                            }
                            desc = f"**User:** {target_user.mention} (`{target_user.id}`)\n"
                            desc += f"**By:** {moderator.mention} (`{moderator.id}`)\n"
                            desc += f"**Reason:** {reason}\n"
                            desc += f"**Via:** Gaza Bot"
                            embed = create_log_embed(
                                f"{action_icons.get(action_type, '⚙️')} {action_titles.get(action_type, 'Mod Action')}",
                                desc,
                                action_colors.get(action_type, discord.Color.blurple()),
                                action_icons.get(action_type, '⚙️')
                            )
                            await self.log(message.guild, "mod", embed=embed)
                            return
            if message.mentions:
                target_user = message.mentions[0]
                moderator = message.author
                desc = f"**User:** {target_user.mention} (`{target_user.id}`)\n"
                desc += f"**By:** {moderator.mention} (`{moderator.id}`)\n"
                desc += f"**Action:** {action_type.title()}\n"
                desc += f"**Via:** Gaza Bot"
                action_icons = {
                    "warn": "⚠️",
                    "jail": "🔒", 
                    "kick": "👢",
                    "ban": "🔨",
                    "mute": "🔇"
                }
                embed = create_log_embed(
                    f"{action_icons.get(action_type, '⚙️')} {action_type.title()} Action",
                    desc,
                    discord.Color.blue(),
                    action_icons.get(action_type, '⚙️')
                )
                await self.log(message.guild, "mod", embed=embed)
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        try:
            if before.roles != after.roles:
                removed_roles = [r for r in before.roles if r not in after.roles]
                added_roles = [r for r in after.roles if r not in before.roles]
                jail_keywords = ["jail", "muted", "timeout", "punished", "restricted"]
                has_jail_role = any(any(keyword in r.name.lower() for keyword in jail_keywords) for r in added_roles)
                has_many_roles_removed = len(removed_roles) > 2
                if has_jail_role and has_many_roles_removed:
                    try:
                        async for entry in after.guild.audit_logs(limit=5, action=discord.AuditLogAction.member_role_update):
                            if entry.target.id == after.id:
                                moderator = entry.user
                                if "gaza" in moderator.name.lower() or "gaza" in getattr(moderator, "display_name", "").lower():
                                    desc = f"**User:** {after.mention} (`{after.id}`)\n"
                                    desc += f"**By:** {moderator.mention} (`{moderator.id}`)\n"
                                    desc += f"**Action:** Jail\n"
                                    desc += f"**Via:** Gaza Bot"
                                    embed = create_log_embed("🔒 User Jailed", desc, discord.Color.dark_gray(), "🔒")
                                    await self.log(after.guild, "mod", embed=embed)
                                    break
                    except Exception:
                        pass
        except Exception:
            traceback.print_exc()

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        try:
            async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.kick):
                if entry.target.id == member.id:
                    moderator = entry.user
                    if "gaza" in moderator.name.lower() or "gaza" in getattr(moderator, "display_name", "").lower():
                        desc = f"**User:** {member.mention} (`{member.id}`)\n"
                        desc += f"**By:** {moderator.mention} (`{moderator.id}`)\n"
                        if entry.reason:
                            desc += f"**Reason:** {entry.reason}\n"
                        desc += f"**Via:** Gaza Bot"
                        embed = create_log_embed("👢 User Kicked", desc, discord.Color.orange(), "👢")
                        await self.log(member.guild, "mod", embed=embed)
                        break
        except Exception:
            pass

# ===========================================================================================
#                                  ERROR HANDLING & CLEANUP
# ===========================================================================================

    @commands.Cog.listener()
    async def on_error(self, event_method, /, *args, **kwargs):
        print(f"[LogsCog] Internal error in {event_method}:")
        traceback.print_exc()

    async def cog_unload(self):
        try:
            await save_data(self.data)
            print("[LogsCog] Saved DB on unload.")
        except Exception:
            traceback.print_exc()

# ===========================================================================================
#                                  SETUP FUNCTION
# ===========================================================================================

async def setup(bot: commands.Bot):
    await init_db()
    await bot.add_cog(LogsCog(bot))

