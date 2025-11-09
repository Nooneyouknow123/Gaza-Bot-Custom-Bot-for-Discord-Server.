# logs_cog.py
# Advanced Logging Cog (discord.py v2) - SQLite Version
# Features:
#  - Separate log channels per category
#  - Message, Reaction, Member, Invite, Role, Channel, Emoji, Voice, Mod command logs
#  - Modern, clean embed styling
#  - SQLite persistence per guild

import discord
from discord.ext import commands
import sqlite3
import os
import datetime

DB_FILE = "logging.db"

# -------------------- SQLITE DATABASE FUNCTIONS --------------------

def init_db():
    """Initialize the SQLite database with required tables"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS guild_logs (
            guild_id TEXT PRIMARY KEY,
            message_channel TEXT,
            member_channel TEXT,
            role_channel TEXT,
            channel_channel TEXT,
            emoji_channel TEXT,
            voice_channel TEXT,
            mod_channel TEXT
        )
    ''')
    
    conn.commit()
    conn.close()

def load_data():
    """Load all guild data from SQLite database"""
    if not os.path.exists(DB_FILE):
        init_db()
        return {}
    
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    data = {}
    c.execute('SELECT * FROM guild_logs')
    rows = c.fetchall()
    
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
                "mod": row[7]
            }
        }
    
    conn.close()
    return data

def save_data(data):
    """Save all guild data to SQLite database"""
    init_db()
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    for guild_id, guild_data in data.items():
        channels = guild_data["channels"]
        c.execute('''
            INSERT OR REPLACE INTO guild_logs 
            (guild_id, message_channel, member_channel, role_channel, channel_channel, emoji_channel, voice_channel, mod_channel)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            guild_id,
            channels.get("message"),
            channels.get("member"),
            channels.get("role"),
            channels.get("channel"),
            channels.get("emoji"),
            channels.get("voice"),
            channels.get("mod")
        ))
    
    conn.commit()
    conn.close()

def ensure_guild(data, guild_id):
    """Ensure guild exists in data"""
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

# -------------------- EMBED UTILITIES --------------------

def create_log_embed(title, description, color, icon=None, author=None, thumbnail=None, inline_footer=False):
    """Enhanced embed creation with better styling"""
    e = discord.Embed(
        title=f"{icon} {title}" if icon else title,
        description=description,
        color=color,
        timestamp=datetime.datetime.utcnow()
    )
    
    footer_text = "🛡️ Server Logs • Advanced Logging System"
    e.set_footer(
        text=footer_text,
        icon_url="https://i.imgur.com/8h7Qq0G.png" if not inline_footer else None
    )
    
    if author:
        e.set_author(name=str(author), icon_url=author.display_avatar.url)
    
    if thumbnail:
        e.set_thumbnail(url=thumbnail)
    
    return e

def format_content(content, max_length=1024):
    """Format content with proper truncation and line handling"""
    if not content:
        return "*(empty)*"
    
    content = content.strip()
    if len(content) > max_length:
        return content[:max_length-3] + "..."
    return content

def create_field_section(embed, title, value, inline=False):
    """Create a beautifully formatted field section"""
    if value:
        if len(value) > 1024:
            value = value[:1021] + "..."
        embed.add_field(
            name=f"📋 {title}",
            value=value,
            inline=inline
        )

# -------------------- LOGS COG --------------------

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
        category_emojis = {
            "message": "💬", "member": "👥", "role": "🎭", 
            "channel": "📁", "emoji": "😀", "voice": "🎵", "mod": "🛡️"
        }
        
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
            "channel": "📁", "emoji": "😀", "voice": "🎵", "mod": "🛡️"
        }
        
        description = ""
        for cat, cid in g["channels"].items():
            status = f"✅ <#{cid}>" if cid else "❌ *(not set)*"
            description += f"{category_emojis.get(cat, '📝')} **{cat.capitalize()}:** {status}\n"
        
        embed = create_log_embed(
            "⚙️ Logging Configuration",
            description,
            discord.Color.blurple()
        )
        embed.add_field(
            name="📖 Usage",
            value="Use `!setlog <category> <channel>` to configure logging",
            inline=False
        )
        
        await ctx.send(embed=embed)

    # ---------------- MESSAGE LOGS ----------------
    
    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if not message.guild or message.author.bot:
            return
        
        desc = (
            f"👤 **Author:** {message.author.mention} (`{message.author.id}`)\n"
            f"📁 **Channel:** {message.channel.mention}\n"
            f"🆔 **Message ID:** `{message.id}`"
        )
        
        embed = create_log_embed(
            "🗑️ Message Deleted", 
            desc, 
            discord.Color.orange(),
            author=message.author
        )
        
        if message.content:
            create_field_section(embed, "Content", format_content(message.content))
        
        if message.attachments:
            urls = "\n".join(f"📎 {a.filename}" for a in message.attachments)
            create_field_section(embed, f"Attachments ({len(message.attachments)})", urls, inline=False)
        
        await self.log(message.guild, "message", embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if not before.guild or before.author.bot or before.content == after.content:
            return
        
        desc = (
            f"👤 **Author:** {before.author.mention}\n"
            f"📁 **Channel:** {before.channel.mention}\n"
            f"🔗 [Jump to Message]({after.jump_url})"
        )
        
        embed = create_log_embed(
            "✏️ Message Edited", 
            desc, 
            discord.Color.orange(),
            author=before.author
        )
        
        create_field_section(embed, "Before", format_content(before.content))
        create_field_section(embed, "After", format_content(after.content))
        
        await self.log(before.guild, "message", embed)

    @commands.Cog.listener()
    async def on_bulk_message_delete(self, messages):
        if not messages:
            return
        
        guild = messages[0].guild
        channel = messages[0].channel
        
        embed = create_log_embed(
            "🧹 Bulk Message Delete", 
            f"📁 **Channel:** {channel.mention}\n"
            f"📊 **Messages Deleted:** `{len(messages)}`\n"
            f"⏰ **Action Time:** {discord.utils.format_dt(discord.utils.utcnow(), 'F')}",
            discord.Color.orange()
        )
        
        await self.log(guild, "message", embed)

    # ---------------- REACTION LOGS ----------------
    
    @commands.Cog.listener()
    async def on_reaction_add(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        
        msg = reaction.message
        desc = (
            f"👤 **User:** {user.mention} (`{user.id}`)\n"
            f"😀 **Emoji:** {reaction.emoji}\n"
            f"📁 **Channel:** {msg.channel.mention}\n"
            f"🔗 [Jump to Message]({msg.jump_url})"
        )
        
        embed = create_log_embed(
            "➕ Reaction Added", 
            desc, 
            discord.Color.green(),
            author=user
        )
        
        await self.log(msg.guild, "message", embed)

    @commands.Cog.listener()
    async def on_reaction_remove(self, reaction, user):
        if user.bot or not reaction.message.guild:
            return
        
        msg = reaction.message
        desc = (
            f"👤 **User:** {user.mention} (`{user.id}`)\n"
            f"😀 **Emoji:** {reaction.emoji}\n"
            f"📁 **Channel:** {msg.channel.mention}\n"
            f"🔗 [Jump to Message]({msg.jump_url})"
        )
        
        embed = create_log_embed(
            "➖ Reaction Removed", 
            desc, 
            discord.Color.orange(),
            author=user
        )
        
        await self.log(msg.guild, "message", embed)

    # ---------------- MEMBER LOGS ----------------
    
    @commands.Cog.listener()
    async def on_member_join(self, member):
        account_age = discord.utils.format_dt(member.created_at, 'R')
        
        embed = create_log_embed(
            "👋 Member Joined", 
            f"👤 **Member:** {member.mention} (`{member.id}`)\n"
            f"📅 **Account Created:** {account_age}\n"
            f"👥 **Member Count:** `{member.guild.member_count}`",
            discord.Color.green(),
            author=member,
            thumbnail=member.display_avatar.url
        )
        
        await self.log(member.guild, "member", embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        roles = ", ".join([r.mention for r in member.roles if r != member.guild.default_role][:10]) or "*(none)*"
        if len([r for r in member.roles if r != member.guild.default_role]) > 10:
            roles += f" *+{len(member.roles) - 10} more*"
        
        embed = create_log_embed(
            "🚪 Member Left", 
            f"👤 **Member:** {member.mention} (`{member.id}`)\n"
            f"👥 **Member Count:** `{member.guild.member_count}`\n"
            f"🎭 **Roles:** {roles}",
            discord.Color.red(),
            author=member,
            thumbnail=member.display_avatar.url
        )
        
        await self.log(member.guild, "member", embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.roles != after.roles:
            added = [r for r in after.roles if r not in before.roles]
            removed = [r for r in before.roles if r not in after.roles]
            
            if added:
                roles_text = ", ".join([r.mention for r in added][:5])
                if len(added) > 5:
                    roles_text += f" *+{len(added) - 5} more*"
                
                embed = create_log_embed(
                    "🎟️ Role Added", 
                    f"👤 **Member:** {after.mention}\n"
                    f"➕ **Roles Added:** {roles_text}",
                    discord.Color.green(),
                    author=after
                )
                await self.log(after.guild, "member", embed)
            
            if removed:
                roles_text = ", ".join([r.mention for r in removed][:5])
                if len(removed) > 5:
                    roles_text += f" *+{len(removed) - 5} more*"
                
                embed = create_log_embed(
                    "❌ Role Removed", 
                    f"👤 **Member:** {after.mention}\n"
                    f"➖ **Roles Removed:** {roles_text}",
                    discord.Color.red(),
                    author=after
                )
                await self.log(after.guild, "member", embed)

    # ---------------- INVITE LOGS ----------------
    
    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        creator = getattr(invite, "inviter", None)
        expires = f"<t:{int((discord.utils.utcnow() + datetime.timedelta(seconds=invite.max_age)).timestamp())}>" if invite.max_age else "Never"
        
        desc = (
            f"🔗 **Code:** `{invite.code}`\n"
            f"📁 **Channel:** {invite.channel.mention}\n"
            f"👤 **Created by:** {creator.mention if creator else 'Unknown'}\n"
            f"🔢 **Max Uses:** {invite.max_uses or '∞'}\n"
            f"⏰ **Expires:** {expires}"
        )
        
        embed = create_log_embed(
            "🔗 Invite Created", 
            desc, 
            discord.Color.green(),
            author=creator
        )
        
        await self.log(invite.guild, "member", embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        desc = (
            f"🔗 **Code:** `{invite.code}`\n"
            f"📁 **Channel:** {invite.channel.mention if invite.channel else 'Unknown'}\n"
            f"🗑️ **Status:** Invite link was deleted"
        )
        
        embed = create_log_embed(
            "❌ Invite Deleted", 
            desc, 
            discord.Color.red()
        )
        
        await self.log(invite.guild, "member", embed)

    # ---------------- ROLE LOGS ----------------
    
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        embed = create_log_embed(
            "➕ Role Created", 
            f"🎭 **Role:** {role.mention}\n"
            f"🆔 **ID:** `{role.id}`\n"
            f"🎨 **Color:** `{str(role.color)}`",
            discord.Color.blurple()
        )
        await self.log(role.guild, "role", embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        embed = create_log_embed(
            "🗑️ Role Deleted", 
            f"🎭 **Role:** `{role.name}`\n"
            f"🆔 **ID:** `{role.id}`",
            discord.Color.blurple()
        )
        await self.log(role.guild, "role", embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if before.color != after.color:
            embed = create_log_embed(
                "🎨 Role Updated", 
                f"🎭 **Role:** {after.mention}\n"
                f"🔄 **Change:** Color updated\n"
                f"🎨 **New Color:** `{str(after.color)}`",
                discord.Color.blurple()
            )
            await self.log(after.guild, "role", embed)

    # ---------------- CHANNEL LOGS ----------------
    
    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        embed = create_log_embed(
            "📢 Channel Created", 
            f"📁 **Channel:** {channel.mention}\n"
            f"🆔 **ID:** `{channel.id}`\n"
            f"📊 **Type:** `{str(channel.type).capitalize()}`",
            discord.Color.teal()
        )
        await self.log(channel.guild, "channel", embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        embed = create_log_embed(
            "🗑️ Channel Deleted", 
            f"📁 **Channel:** `#{channel.name}`\n"
            f"🆔 **ID:** `{channel.id}`\n"
            f"📊 **Type:** `{str(channel.type).capitalize()}`",
            discord.Color.teal()
        )
        await self.log(channel.guild, "channel", embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        embed = create_log_embed(
            "⚙️ Channel Updated", 
            f"📁 **Channel:** {after.mention}\n"
            f"📝 **Changes:** Permissions or settings modified",
            discord.Color.teal()
        )
        await self.log(after.guild, "channel", embed)

    # ---------------- EMOJI LOGS ----------------
    
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        added = [e for e in after if e not in before]
        removed = [e for e in before if e not in after]
        
        if added:
            embed = create_log_embed(
                "😀 Emoji Added",
                f"🎉 Added: {', '.join(e.name for e in added)}\n📊 Total Emojis: `{len(after)}`",
                discord.Color.gold()
            )
            await self.log(guild, "emoji", embed)
        
        if removed:
            embed = create_log_embed(
                "❌ Emoji Removed",
                f"🗑️ Removed: {', '.join(e.name for e in removed)}\n📊 Total Emojis: `{len(after)}`",
                discord.Color.gold()
            )
            await self.log(guild, "emoji", embed)

    # ---------------- VOICE LOGS ----------------
    
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel != after.channel:
            if after.channel and not before.channel:
                desc = f"👤 **Member:** {member.mention}\n🎤 Joined Voice: {after.channel.mention}"
                embed = create_log_embed("🎵 Voice Joined", desc, discord.Color.green(), author=member)
            elif before.channel and not after.channel:
                desc = f"👤 **Member:** {member.mention}\n🎤 Left Voice: {before.channel.mention}"
                embed = create_log_embed("🎵 Voice Left", desc, discord.Color.orange(), author=member)
            else:
                desc = f"👤 **Member:** {member.mention}\n🎤 Moved from {before.channel.mention} to {after.channel.mention}"
                embed = create_log_embed("🎵 Voice Moved", desc, discord.Color.blurple(), author=member)
            
            await self.log(member.guild, "voice", embed)

# -------------------- SETUP --------------------

async def setup(bot):
    init_db()
    await bot.add_cog(LogsCog(bot))
