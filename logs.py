# logs_cog.py
# Advanced Logging Cog (discord.py v2)
# Features:
#  - Separate log channels per category
#  - Message, Reaction, Member, Invite, Role, Channel, Emoji, Voice, Mod command logs
#  - Modern, clean embed styling
#  - JSON persistence per guild

import discord
from discord.ext import commands
import json
import os
import datetime

DATA_FILE = "logs_data.json"


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def ensure_guild(data, guild_id):
    gid = str(guild_id)
    if gid not in data:
        data[gid] = {
            "channels": {
                "message": None,
                "member": None,
                "role": None,
                "channel": None,
                "emoji": None,
                "voice": None,
                "mod": None
            }
        }
    return data[gid]


def create_log_embed(title, description, color, icon=None):
    e = discord.Embed(
        title=f"{icon or ''} {title}",
        description=description,
        color=color,
        timestamp=datetime.datetime.utcnow()
    )
    e.set_footer(text="Server Logs • v1")
    return e


class LogsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.data = load_data()

    async def save(self):
        save_data(self.data)

    def guild_conf(self, guild_id):
        return ensure_guild(self.data, guild_id)

    async def log(self, guild: discord.Guild, category: str, embed: discord.Embed):
        g = self.guild_conf(guild.id)
        chan_id = g["channels"].get(category)
        if not chan_id:
            return
        channel = guild.get_channel(int(chan_id))
        if not channel:
            return
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    # ---------------- SETUP COMMANDS ----------------
    @commands.command(name="setlog")
    @commands.has_permissions(administrator=True)
    async def set_log_channel(self, ctx, category: str, channel: discord.TextChannel):
        valid = ["message", "member", "role", "channel", "emoji", "voice", "mod"]
        if category not in valid:
            await ctx.send(
                embed=create_log_embed(
                    "Invalid Category",
                    f"Valid categories: {', '.join(valid)}",
                    discord.Color.red(),
                    "⚠️"
                )
            )
            return
        g = self.guild_conf(ctx.guild.id)
        g["channels"][category] = str(channel.id)
        await self.save()
        await ctx.send(
            embed=create_log_embed(
                "Log Channel Set",
                f"{category.capitalize()} logs will be sent to {channel.mention}",
                discord.Color.green(),
                "✅"
            )
        )

    @commands.command(name="logconfig")
    @commands.has_permissions(administrator=True)
    async def log_config(self, ctx):
        g = self.guild_conf(ctx.guild.id)
        msg = ""
        for cat, cid in g["channels"].items():
            ch = f"<#{cid}>" if cid else "(not set)"
            msg += f"**{cat.capitalize()} Logs:** {ch}\n"
        await ctx.send(embed=create_log_embed("Log Configuration", msg, discord.Color.blurple(), "⚙️"))

    # ---------------- MESSAGE LOGS ----------------
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        desc = f"**Author:** {message.author} ({message.author.id})\n**Channel:** {message.channel.mention}\n**Message ID:** `{message.id}`"
        embed = create_log_embed("Message Deleted", desc, discord.Color.orange(), "🗑️")
        if message.content:
            embed.add_field(name="Content", value=message.content[:1024])
        if message.attachments:
            urls = "\n".join(a.url for a in message.attachments)
            embed.add_field(name="Attachments", value=urls, inline=False)
        await self.log(message.guild, "message", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot:
            return
        if before.content == after.content:
            return
        desc = f"**Author:** {before.author}\n**Channel:** {before.channel.mention}"
        embed = create_log_embed("Message Edited", desc, discord.Color.orange(), "✏️")
        embed.add_field(name="Before", value=before.content[:1024] or "(empty)", inline=False)
        embed.add_field(name="After", value=after.content[:1024] or "(empty)", inline=False)
        await self.log(before.guild, "message", embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        guild = messages[0].guild
        channel = messages[0].channel
        embed = create_log_embed("Bulk Message Delete", f"**Channel:** {channel.mention}\n**Count:** {len(messages)}", discord.Color.orange(), "🧹")
        await self.log(guild, "message", embed)

    #  REACTION LOGS 
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        msg = reaction.message
        desc = (
            f"**User:** {user.mention} ({user.id})\n"
            f"**Emoji:** {reaction.emoji}\n"
            f"**Channel:** {msg.channel.mention}\n"
            f"[Jump to Message]({msg.jump_url})"
        )
        embed = create_log_embed("Reaction Added", desc, discord.Color.orange(), "➕")
        await self.log(msg.guild, "message", embed)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        msg = reaction.message
        desc = (
            f"**User:** {user.mention} ({user.id})\n"
            f"**Emoji:** {reaction.emoji}\n"
            f"**Channel:** {msg.channel.mention}\n"
            f"[Jump to Message]({msg.jump_url})"
        )
        embed = create_log_embed("Reaction Removed", desc, discord.Color.orange(), "➖")
        await self.log(msg.guild, "message", embed)

    # ---------------- MEMBER LOGS ----------------
    @commands.Cog.listener()
    async def on_member_join(self, member):
        embed = create_log_embed("Member Joined", f"{member.mention} ({member.id}) joined the server.", discord.Color.green(), "👋")
        embed.set_thumbnail(url=member.display_avatar.url)
        await self.log(member.guild, "member", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        roles = ", ".join([r.name for r in member.roles if r != member.guild.default_role]) or "(none)"
        desc = f"{member.mention} ({member.id}) left the server.\n**Roles:** {roles}"
        embed = create_log_embed("Member Left", desc, discord.Color.red(), "🚪")
        await self.log(member.guild, "member", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            if added:
                embed = create_log_embed("Role Added", f"**{after.mention}** received: {', '.join([r.name for r in added])}", discord.Color.green(), "🎟️")
                await self.log(after.guild, "member", embed)
            if removed:
                embed = create_log_embed("Role Removed", f"**{after.mention}** lost: {', '.join([r.name for r in removed])}", discord.Color.red(), "❌")
                await self.log(after.guild, "member", embed)

    #  INVITE LOGS 
    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        creator = getattr(invite, "inviter", None)
        desc = (
            f"**Code:** `{invite.code}`\n"
            f"**Channel:** {invite.channel.mention}\n"
            f"**Max Uses:** {invite.max_uses or '∞'}\n"
            f"**Expires:** {invite.max_age or 'Never'} seconds\n"
            f"**Created by:** {creator.mention if creator else 'Unknown'}"
        )
        embed = create_log_embed("Invite Created", desc, discord.Color.green(), "🔗")
        await self.log(invite.guild, "member", embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        desc = f"**Code:** `{invite.code}` was deleted.\n**Channel:** {invite.channel.mention if invite.channel else 'Unknown'}"
        embed = create_log_embed("Invite Deleted", desc, discord.Color.red(), "❌")
        await self.log(invite.guild, "member", embed)

    # ---------------- ROLE LOGS ----------------
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        embed = create_log_embed("Role Created", f"**{role.name}** ({role.id}) was created.", discord.Color.blurple(), "➕")
        await self.log(role.guild, "role", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        embed = create_log_embed("Role Deleted", f"**{role.name}** ({role.id}) was deleted.", discord.Color.blurple(), "🗑️")
        await self.log(role.guild, "role", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if before.color != after.color:
            embed = create_log_embed("Role Updated", f"**{before.name}** color changed.", discord.Color.blurple(), "🎨")
            await self.log(after.guild, "role", embed)

    # ---------------- CHANNEL LOGS ----------------
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        embed = create_log_embed("Channel Created", f"{channel.mention} ({channel.id}) was created.", discord.Color.teal(), "📢")
        await self.log(channel.guild, "channel", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        embed = create_log_embed("Channel Deleted", f"#{channel.name} ({channel.id}) was deleted.", discord.Color.teal(), "🗑️")
        await self.log(channel.guild, "channel", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        embed = create_log_embed("Channel Updated", f"{after.mention} permissions or settings were changed.", discord.Color.teal(), "⚙️")
        await self.log(after.guild, "channel", embed)

    # ---------------- EMOJI LOGS ----------------
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        before_names = {e.name for e in before}
        after_names = {e.name for e in after}
        if len(before) < len(after):
            embed = create_log_embed("Emoji Created", "A new emoji was added.", discord.Color.gold(), "😀")
        elif len(before) > len(after):
            embed = create_log_embed("Emoji Deleted", "An emoji was removed.", discord.Color.gold(), "❌")
        elif before_names != after_names:
            embed = create_log_embed("Emoji Renamed", "An emoji name was changed.", discord.Color.gold(), "✏️")
        else:
            return
        await self.log(guild, "emoji", embed)

    # ---------------- VOICE LOGS ----------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel is None and after.channel:
            embed = create_log_embed("Voice Join", f"{member.mention} joined {after.channel.mention}", discord.Color.purple(), "🎧")
        elif after.channel is None and before.channel:
            embed = create_log_embed("Voice Leave", f"{member.mention} left {before.channel.mention}", discord.Color.purple(), "🎤")
        elif before.channel and after.channel and before.channel != after.channel:
            mbed = create_log_embed("Voice Move", f"{member.mention} moved from {before.channel.mention} → {after.channel.mention}", discord.Color.purple(), "🎙️")
        else:
            return
        await self.log(member.guild, "voice", embed)

   

async def setup(bot):
    await bot.add_cog(LogsCog(bot))