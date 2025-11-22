# jail_cog_combined.py

"""

Stabile Jail Cog - vollständige Version mit integriertem Appeal-System

Enthält:

- DB helpers (sqlite)

- Jail/Unjail commands

- Timeout checker for automatic unjail

- Appeals/ticket system (create appeal button, approve/deny/close handlers)

- Views for CreateAppeal and Ticket actions

Bitte prüfe die Konfiguration (DB_FILE path, permissions) bevor du den Cog produktiv einsetzt.

"""

import discord

from discord.ext import commands, tasks

from discord.ui import View, Button

import asyncio

import sqlite3

import os

import datetime

import json

import traceback

import logging

from typing import Optional, Callable, Any

# ---------------- Config ----------------

DB_FILE = "jail_system.db"

TRANSCRIPT_TEMP_DIR = "transcripts"

DEFAULT_CATEGORY_NAME = "🔒 Jail"

APPEALS_CHANNEL_NAME = "appeals"

ADMIN_CHANNEL_NAME = "jail-admins"

JAILED_ROLE_NAME = "Jailed"

TICKET_PREFIX = "appeal-"

APPEAL_PROMPT_TIMEOUT = 600  # seconds

ERROR_LOG_FILE = "jail_errors.log"

# Setup logging

logger = logging.getLogger("jail_cog")

if not logger.handlers:

    handler = logging.FileHandler(ERROR_LOG_FILE, encoding="utf-8")

    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

    handler.setFormatter(formatter)

    logger.addHandler(handler)

    logger.setLevel(logging.INFO)

# Helper time

def now_iso():

    return datetime.datetime.utcnow().isoformat()

def pretty_ts(dt: Optional[datetime.datetime] = None):

    dt = dt or datetime.datetime.utcnow()

    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

# duration parser

def parse_duration(s: str) -> Optional[int]:

    try:

        s = s.lower().strip()

        if s.endswith("m"):

            return int(s[:-1]) * 60

        if s.endswith("h"):

            return int(s[:-1]) * 3600

        if s.endswith("d"):

            return int(s[:-1]) * 86400

        if s.isdigit():

            return int(s) * 60

    except Exception:

        return None

    return None

# UI Views

class CreateAppealView(View):

    def __init__(self, cog):

        super().__init__(timeout=None)

        self.cog = cog

        self.add_item(Button(label="📩 Create Appeal", style=discord.ButtonStyle.primary, custom_id="create_appeal"))

class TicketActionView(View):

    def __init__(self, cog):

        super().__init__(timeout=None)

        self.cog = cog

        self.add_item(Button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id="ticket_approve"))

        self.add_item(Button(label="❌ Deny", style=discord.ButtonStyle.danger, custom_id="ticket_deny"))

        self.add_item(Button(label="🔒 Close", style=discord.ButtonStyle.secondary, custom_id="ticket_close"))

# The Cog

class JailCog(commands.Cog):

    def __init__(self, bot: commands.Bot):

        self.bot = bot

        os.makedirs(TRANSCRIPT_TEMP_DIR, exist_ok=True)

        self._db_lock = asyncio.Lock()

        self._timeout_lock = asyncio.Lock()

        # create connection (thread-safe usage: check_same_thread=False)

        self.conn = None

        self._ensure_db()

        # cache for open tickets

        self.ticket_channel_cache = set()

        # load open tickets from DB (sync; safe during init because conn exists)

        try:

            self._load_open_tickets()

        except Exception:

            logger.exception("Failed to load initial open tickets")

        logger.info("JailCog initialized")

    # ------------------ DB helpers ------------------

    def _ensure_db(self):

        """

        Ensure DB exists and create tables. This is synchronous and executed at cog init.

        """

        try:

            self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)

            self.conn.row_factory = sqlite3.Row

            c = self.conn.cursor()

            c.execute("""

            CREATE TABLE IF NOT EXISTS guild_config (

                guild_id INTEGER PRIMARY KEY,

                jail_role INTEGER,

                jail_category INTEGER,

                appeals_channel INTEGER,

                admin_channel INTEGER,

                admin_role INTEGER

            )""")

            c.execute("""

            CREATE TABLE IF NOT EXISTS jailed_users (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                guild_id INTEGER,

                user_id INTEGER,

                reason TEXT,

                previous_roles TEXT,

                jailed_at TEXT,

                release_at TEXT

            )""")

            c.execute("""

            CREATE TABLE IF NOT EXISTS appeals (

                id INTEGER PRIMARY KEY AUTOINCREMENT,

                guild_id INTEGER,

                ticket_channel_id INTEGER,

                user_id INTEGER,

                reason TEXT,

                status TEXT,

                created_at TEXT,

                closed_at TEXT,

                transcript TEXT

            )""")

            self.conn.commit()

        except Exception as e:

            logger.exception("Failed to ensure DB: %s", e)

            # try to recreate connection

            try:

                if self.conn:

                    self.conn.close()

            except Exception:

                pass

            self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)

            self.conn.row_factory = sqlite3.Row

    def _get_conn(self):

        """

        Return a live connection, reconnect if needed.

        This is synchronous and used by sync DB functions.

        """

        try:

            if self.conn is None:

                self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)

                self.conn.row_factory = sqlite3.Row

            # simple health-check

            self.conn.execute("SELECT 1")

            return self.conn

        except Exception:

            try:

                if self.conn:

                    self.conn.close()

            except Exception:

                pass

            logger.warning("Reconnecting DB connection")

            self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)

            self.conn.row_factory = sqlite3.Row

            return self.conn

    async def _run_db(self, fn: Callable[..., Any], *args, **kwargs) -> Any:

        """

        Run a synchronous DB function in an executor while holding an asyncio.Lock.

        fn will be called with the DB connection as its first parameter.

        This prevents blocking the event loop for DB operations and avoids double-locks.

        """

        async with self._db_lock:

            loop = asyncio.get_running_loop()

            conn = self._get_conn()

            # wrap into a callable that passes conn as first arg

            def _callable():

                try:

                    return fn(conn, *args, **kwargs)

                except Exception:

                    # propagate exception to be handled by run_in_executor result

                    logger.exception("DB function raised an exception")

                    raise

            return await loop.run_in_executor(None, _callable)

    # ---------- Sync DB functions (take conn param) ----------

    def _save_guild_config_sync(self, conn, gid: int, **kw):

        c = conn.cursor()

        existing = c.execute("SELECT 1 FROM guild_config WHERE guild_id=?", (gid,)).fetchone()

        if existing:

            fields = ", ".join(f"{k}=?" for k in kw.keys())

            values = list(kw.values()) + [gid]

            c.execute(f"UPDATE guild_config SET {fields} WHERE guild_id=?", values)

        else:

            keys = ["jail_role", "jail_category", "appeals_channel", "admin_channel", "admin_role"]

            vals = [kw.get(k) for k in keys]

            c.execute("INSERT INTO guild_config (guild_id, jail_role, jail_category, appeals_channel, admin_channel, admin_role) VALUES (?,?,?,?,?,?)", [gid] + vals)

        conn.commit()

    def _get_guild_config_sync(self, conn, gid: int):

        c = conn.cursor()

        r = c.execute("SELECT * FROM guild_config WHERE guild_id=?", (gid,)).fetchone()

        return dict(r) if r else None

    def _add_jailed_user_sync(self, conn, gid: int, uid: int, reason: str, prev_roles, release_at=None):

        c = conn.cursor()

        c.execute(

            "INSERT INTO jailed_users (guild_id,user_id,reason,previous_roles,jailed_at,release_at) VALUES (?,?,?,?,?,?)",

            (gid, uid, reason, json.dumps(prev_roles), now_iso(), release_at)

        )

        conn.commit()

        return c.lastrowid

    def _get_jailed_user_sync(self, conn, gid: int, uid: int):

        c = conn.cursor()

        r = c.execute("SELECT * FROM jailed_users WHERE guild_id=? AND user_id=?", (gid, uid)).fetchone()

        return dict(r) if r else None

    def _remove_jailed_user_sync(self, conn, gid: int, uid: int):

        c = conn.cursor()

        c.execute("DELETE FROM jailed_users WHERE guild_id=? AND user_id=?", (gid, uid))

        conn.commit()

        return True

    def _create_appeal_sync(self, conn, guild_id: int, ticket_channel_id: int, user_id: int, reason: str):

        c = conn.cursor()

        c.execute("INSERT INTO appeals (guild_id, ticket_channel_id, user_id, reason, status, created_at) VALUES (?,?,?,?,?,?)",

                  (guild_id, ticket_channel_id, user_id, reason, "open", now_iso()))

        conn.commit()

        return c.lastrowid

    def _close_appeal_sync(self, conn, ticket_channel_id: int, status: str, transcript_text: str):

        c = conn.cursor()

        c.execute("UPDATE appeals SET status = ?, transcript = ?, closed_at = ? WHERE ticket_channel_id = ?", (status, transcript_text, now_iso(), ticket_channel_id))

        conn.commit()

        return True

    def _get_appeals_for_user_sync(self, conn, guild_id: int, user_id: int, limit: int = 10):

        c = conn.cursor()

        rows = c.execute("SELECT * FROM appeals WHERE guild_id = ? AND user_id = ? ORDER BY created_at DESC LIMIT ?", (guild_id, user_id, limit)).fetchall()

        return [dict(r) for r in rows]

    def _load_open_tickets(self):

        """

        Synchronous loader used at init: reads open tickets into cache.

        (This is not run in executor because it's called during __init__ and uses the same thread)

        """

        try:

            c = self._get_conn().cursor()

            rows = c.execute("SELECT ticket_channel_id FROM appeals WHERE status = 'open'").fetchall()

            for r in rows:

                if r[0]:

                    self.ticket_channel_cache.add(r[0])

        except Exception:

            logger.exception("Failed to load open tickets")

    # ------------------ Logging helper ------------------

    async def _log_mod(self, guild: discord.Guild, *, embed: discord.Embed = None, file: discord.File = None, content: str = None):

        """

        Safe mod logging. Only await if the log function is a coroutine.

        """

        try:

            logs_cog = self.bot.get_cog("LogsCog")

            if logs_cog and hasattr(logs_cog, "log") and callable(logs_cog.log):

                coro = logs_cog.log(guild, "mod", embed=embed, file=file, content=content)

                if asyncio.iscoroutine(coro):

                    await coro

                else:

                    logger.info("LogsCog.log is not async; logged manually: %s", content or (embed.title if embed else "embed"))

            else:

                logger.info("Mod log for guild %s: %s", guild.id, content or (embed.title if embed else "embed"))

        except Exception:

            logger.exception("_log_mod failed")

    # transcript

    async def _make_transcript_file(self, channel: discord.TextChannel, member_id: int, appeal_id: int) -> str:

        safe_member = str(member_id)

        filename = os.path.join(TRANSCRIPT_TEMP_DIR, f"transcript_{safe_member}_{appeal_id}.txt")

        lines = []

        try:

            async for m in channel.history(limit=1000, oldest_first=True):

                ts = m.created_at.strftime("%Y-%m-%d %H:%M:%S UTC") if m.created_at else "?"

                content = m.content or ""

                lines.append(f"[{ts}] {m.author} ({m.author.id}): {content}")

            with open(filename, "w", encoding="utf-8") as f:

                f.write("\n".join(lines))

        except Exception:

            logger.exception("Failed to create transcript for channel %s", getattr(channel, "id", "?"))

        return filename

    # ------------------ Permission helpers ------------------

    def _is_jail_admin(self, member: discord.Member) -> bool:

        cfg = self._get_guild_config_sync(self._get_conn(), member.guild.id) or {}

        role_id = cfg.get("admin_role")

        if not role_id:

            return member.guild_permissions.administrator

        role = member.guild.get_role(int(role_id))

        try:

            return (role in member.roles) or member.guild_permissions.administrator if role else member.guild_permissions.administrator

        except Exception:

            return member.guild_permissions.administrator

    def _bot_can_manage_roles(self, guild: discord.Guild) -> bool:

        me = guild.me

        if not me:

            return False

        return me.guild_permissions.manage_roles

    def _bot_role_position_ok(self, guild: discord.Guild, target_role: discord.Role) -> bool:

        me = guild.me

        if not me or not target_role:

            return False

        try:

            return me.top_role.position > target_role.position

        except Exception:

            return False

    # ------------------ Setup commands ------------------

    @commands.command(name="setupjail")

    @commands.has_permissions(administrator=True)

    async def setup_jail(self, ctx: commands.Context):

        guild = ctx.guild

        try:

            jail_role = discord.utils.get(guild.roles, name=JAILED_ROLE_NAME)

            if not jail_role:

                jail_role = await guild.create_role(name=JAILED_ROLE_NAME, reason="Jail setup by bot")

            category = discord.utils.get(guild.categories, name=DEFAULT_CATEGORY_NAME)

            if not category:

                category = await guild.create_category(DEFAULT_CATEGORY_NAME, reason="Jail setup by bot")

            appeals_chan = discord.utils.get(guild.text_channels, name=APPEALS_CHANNEL_NAME)

            if not appeals_chan:

                overwrites = {

                    guild.default_role: discord.PermissionOverwrite(read_messages=True, send_messages=False),

                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)

                }

                appeals_chan = await guild.create_text_channel(APPEALS_CHANNEL_NAME, category=category, overwrites=overwrites, reason="Jail setup appeals channel")

            admin_chan = discord.utils.get(guild.text_channels, name=ADMIN_CHANNEL_NAME)

            if not admin_chan:

                overwrites = {

                    guild.default_role: discord.PermissionOverwrite(read_messages=False),

                    guild.me: discord.PermissionOverwrite(read_messages=True, send_messages=True)

                }

                admin_chan = await guild.create_text_channel(ADMIN_CHANNEL_NAME, category=category, overwrites=overwrites, reason="Jail setup admin channel")

            # Save config to DB via async wrapper

            await self._run_db(self._save_guild_config_sync, guild.id,

                               jail_role=jail_role.id, jail_category=category.id, appeals_channel=appeals_chan.id, admin_channel=admin_chan.id, admin_role=None)

            embed = discord.Embed(title="📩 Appeals", description="If you are jailed and want to appeal, click **Create Appeal** below and follow the instructions.", color=discord.Color.blurple(), timestamp=datetime.datetime.utcnow())

            embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)

            embed.set_footer(text="Appeal system • Click the button to start")

            view = CreateAppealView(self)

            try:

                async for m in appeals_chan.history(limit=50):

                    if m.author == guild.me and m.embeds:

                        try:

                            await m.delete()

                        except Exception:

                            pass

                await appeals_chan.send(embed=embed, view=view)

            except Exception:

                logger.exception("Failed to post appeals message")

            le = discord.Embed(title="🛠️ Jail System Setup", description=f"Jail system created by {ctx.author.mention}", color=discord.Color.blurple(), timestamp=datetime.datetime.utcnow())

            le.add_field(name="Jail Role", value=jail_role.mention)

            le.add_field(name="Appeals Channel", value=appeals_chan.mention)

            le.add_field(name="Admin Channel", value=admin_chan.mention)

            le.set_footer(text=f"Setup at {pretty_ts()}")

            await self._log_mod(guild, embed=le)

            await ctx.send(embed=discord.Embed(title="Jail system", description="Setup complete. Appeals button posted.", color=discord.Color.green()))

        except Exception as e:

            logger.exception("setup_jail failed")

            await ctx.send(embed=discord.Embed(title="Error", description=f"Setup failed: {e}", color=discord.Color.red()))

    # ------------------ Setup commands ------------------

    @commands.command(name="setjailadmins")

    @commands.has_permissions(administrator=True)

    async def set_jail_admins(self, ctx: commands.Context, role: discord.Role):

        """Set a role as Jail Admins"""

        try:

            guild = ctx.guild

            cfg = await self._run_db(self._get_guild_config_sync, guild.id) or {}

            # Speichere Role-ID sicher

            await self._run_db(self._save_guild_config_sync,

                               guild.id,

                               jail_role=cfg.get("jail_role"),

                               jail_category=cfg.get("jail_category"),

                               appeals_channel=cfg.get("appeals_channel"),

                               admin_channel=cfg.get("admin_channel"),

                               admin_role=role.id if role else None)

            await ctx.send(embed=discord.Embed(

                title="Jail Admins Set",

                description=f"Role {role.mention} set as jail admins.",

                color=discord.Color.green()

            ))

            # Log

            le = discord.Embed(

                title="👮 Jail Admin Role Updated",

                description=f"{role.mention} set as jail admins by {ctx.author.mention}",

                color=discord.Color.blurple(),

                timestamp=datetime.datetime.utcnow()

            )

            le.set_footer(text=pretty_ts())

            await self._log_mod(guild, embed=le)

        except Exception:

            logger.exception("set_jail_admins failed")

            await ctx.send(embed=discord.Embed(

                title="Error",

                description="Could not set jail admins.",

                color=discord.Color.red()

            ))

    # ------------------ Jail command ------------------

    @commands.command(name="jail")

    async def cmd_jail(self, ctx: commands.Context, member: discord.Member, duration: Optional[str] = None, *, reason: str = "No reason provided"):

        """Jail a member with optional duration"""

        try:

            # Permission check

            if not self._is_jail_admin(ctx.author):

                return await ctx.send(embed=discord.Embed(

                    title="Not allowed",

                    description="Only Jail Admins or Admins can jail.",

                    color=discord.Color.red()

                ))

            guild = ctx.guild

            cfg = await self._run_db(self._get_guild_config_sync, guild.id)

            if not cfg or not cfg.get("jail_role"):

                return await ctx.send(embed=discord.Embed(

                    title="Not configured",

                    description="Use .setupjail first.",

                    color=discord.Color.red()

                ))

            jail_role = guild.get_role(int(cfg["jail_role"]))

            if not jail_role:

                return await ctx.send(embed=discord.Embed(

                    title="Missing role",

                    description="Configured jail role not found.",

                    color=discord.Color.red()

                ))

            # Already jailed?

            jailed = await self._run_db(self._get_jailed_user_sync, guild.id, member.id)

            if jailed:

                return await ctx.send(embed=discord.Embed(

                    title="Already jailed",

                    description=f"{member.mention} is already jailed.",

                    color=discord.Color.orange()

                ))

            # Parse duration

            release_at = None

            if duration:

                secs = parse_duration(duration)

                if secs:

                    release_at = (datetime.datetime.utcnow() + datetime.timedelta(seconds=secs)).isoformat()

                else:

                    reason = f"{duration} {reason}"

            # Save previous roles to restore later

            prev_roles = [r.id for r in member.roles if r != guild.default_role and r != jail_role]

            roles_to_remove = [r for r in member.roles if r != guild.default_role and r != jail_role]

            # Bot permission checks

            if not self._bot_can_manage_roles(guild):

                return await ctx.send(embed=discord.Embed(

                    title="Missing Permission",

                    description="I need Manage Roles permission.",

                    color=discord.Color.red()

                ))

            if not self._bot_role_position_ok(guild, jail_role):

                return await ctx.send(embed=discord.Embed(

                    title="Role position issue",

                    description="My top role must be above the jail role.",

                    color=discord.Color.red()

                ))

            # Remove previous roles and add jail role

            if roles_to_remove:

                try:

                    await member.remove_roles(*roles_to_remove, reason=f"Jailed by {ctx.author}: {reason}")

                except Exception:

                    # if removing roles fails, continue but log

                    logger.exception("Failed to remove previous roles from %s", member)

            try:

                await member.add_roles(jail_role, reason=f"Jailed by {ctx.author}: {reason}")

            except Exception:

                logger.exception("Failed to add jail role to %s", member)

                return await ctx.send(embed=discord.Embed(title="Error", description="Could not assign jail role.", color=discord.Color.red()))

            # Save to DB safely via executor-wrapped _run_db

            try:

                await self._run_db(self._add_jailed_user_sync, guild.id, member.id, reason, prev_roles, release_at)

            except Exception:

                logger.exception("Failed to add jailed user to DB")

                # attempt to rollback role change (best-effort)

                try:

                    if jail_role in member.roles:

                        await member.remove_roles(jail_role, reason="Rollback after DB failure")

                    if prev_roles:

                        roles_objs = [guild.get_role(rid) for rid in prev_roles if guild.get_role(rid)]

                        if roles_objs:

                            await member.add_roles(*roles_objs, reason="Rollback after DB failure")

                except Exception:

                    logger.exception("Rollback failed")

                return await ctx.send(embed=discord.Embed(

                    title="Error",

                    description="Jailing failed (DB issue).",

                    color=discord.Color.red()

                ))

            # Verify DB

            jailed_check = await self._run_db(self._get_jailed_user_sync, guild.id, member.id)

            if not jailed_check:

                # DB didn't return the record after insert

                logger.error("DB missing record after insert for %s in %s", member.id, guild.id)

                return await ctx.send(embed=discord.Embed(

                    title="Error",

                    description="Jailing failed (DB record missing).",

                    color=discord.Color.red()

                ))

            # DM user

            release_text = f"\nRelease at: {release_at}" if release_at else ""

            try:

                await member.send(f"You were jailed in {guild.name} by {ctx.author}. Reason: {reason}{release_text}")

            except Exception:

                pass

            # Confirmation message

            await ctx.send(embed=discord.Embed(

                title="User Jailed",

                description=f"{member.mention} jailed successfully.",

                color=discord.Color.green()

            ))

            # Mod log

            le = discord.Embed(

                title="🚨 User Jailed",

                description=f"{member.mention} jailed by {ctx.author.mention}",

                color=discord.Color.blurple(),

                timestamp=datetime.datetime.utcnow()

            )

            le.add_field(name="Reason", value=reason)

            if release_at:

                le.add_field(name="Release at", value=release_at)

            await self._log_mod(guild, embed=le)

        except Exception:

            logger.exception("cmd_jail failed")

            await ctx.send(embed=discord.Embed(title="Error", description="Jailing failed.", color=discord.Color.red()))

    # ------------------ Unjail command ------------------

    @commands.command(name="unjail")

    async def cmd_unjail(self, ctx: commands.Context, member: discord.Member):

        try:

            if not self._is_jail_admin(ctx.author):

                return await ctx.send(embed=discord.Embed(

                    title="Not allowed",

                    description="Only Jail Admins or Admins can unjail.",

                    color=discord.Color.red()

                ))

            guild = ctx.guild

            cfg = await self._run_db(self._get_guild_config_sync, guild.id)

            jail_role = guild.get_role(cfg.get("jail_role")) if cfg else None

            if not jail_role or jail_role not in member.roles:

                return await ctx.send(embed=discord.Embed(

                    title="Not jailed",

                    description=f"{member.mention} is not jailed.",

                    color=discord.Color.orange()

                ))

            jailed = await self._run_db(self._get_jailed_user_sync, guild.id, member.id)

            prev_roles = []

            if jailed and jailed.get("previous_roles"):

                for rid in json.loads(jailed["previous_roles"]):

                    r = guild.get_role(rid)

                    if r and self._bot_role_position_ok(guild, r):

                        prev_roles.append(r)

            # Remove jail role

            if jail_role in member.roles:

                try:

                    await member.remove_roles(jail_role, reason=f"Unjailed by {ctx.author}")

                except Exception:

                    logger.exception("Failed to remove jail role from %s", member)

            # Restore previous roles

            if prev_roles:

                try:

                    await member.add_roles(*prev_roles, reason=f"Unjailed by {ctx.author}")

                except Exception:

                    logger.exception("Failed to restore roles to %s", member)

            # Remove from DB

            try:

                await self._run_db(self._remove_jailed_user_sync, guild.id, member.id)

            except Exception:

                logger.exception("Failed to remove jailed user from DB")

            await ctx.send(embed=discord.Embed(

                title="User Unjailed",

                description=f"{member.mention} unjailed successfully.",

                color=discord.Color.green()

            ))

            try:

                await member.send(f"You were unjailed in {guild.name} by {ctx.author}.")

            except Exception:

                pass

            le = discord.Embed(

                title="✅ User Unjailed",

                description=f"{member.mention} unjailed by {ctx.author.mention}",

                color=discord.Color.blurple(),

                timestamp=datetime.datetime.utcnow()

            )

            await self._log_mod(guild, embed=le)

        except Exception:

            logger.exception("cmd_unjail failed")

            await ctx.send(embed=discord.Embed(title="Error", description="Unjailing failed.", color=discord.Color.red()))

    @commands.command()

    async def check_jail(self, ctx, member: discord.Member):

        jailed = await self._run_db(self._get_jailed_user_sync, ctx.guild.id, member.id)

        await ctx.send(f"DB record: {jailed}")

    # ------------------ Background timeout check ------------------

    @tasks.loop(seconds=30)

    async def check_timeouts(self):

        async with self._timeout_lock:

            try:

                # fetch rows with release_at not null

                def _fetch_due(conn):

                    c = conn.cursor()

                    rows = c.execute("SELECT * FROM jailed_users WHERE release_at IS NOT NULL").fetchall()

                    return [dict(r) for r in rows]

                rows = await self._run_db(lambda conn: _fetch_due(conn))

                now = datetime.datetime.utcnow()

                for r in rows:

                    try:

                        release_dt = datetime.datetime.fromisoformat(r["release_at"]) 

                    except Exception:

                        # malformed date -> remove entry to avoid stuck jail

                        logger.exception("Invalid release_at for jailed user: %s", r)

                        await self._run_db(self._remove_jailed_user_sync, r["guild_id"], r["user_id"])

                        continue

                    if release_dt <= now:

                        guild = self.bot.get_guild(r["guild_id"])

                        if guild:

                            member = guild.get_member(r["user_id"])

                            if member:

                                cfg = await self._run_db(self._get_guild_config_sync, guild.id)

                                jail_role = guild.get_role(cfg["jail_role"]) if cfg else None

                                prev_roles = []

                                try:

                                    prev_roles = [guild.get_role(rid) for rid in json.loads(r["previous_roles"]) if guild.get_role(rid)]

                                except Exception:

                                    logger.exception("Failed to parse previous_roles during automatic unjail for %s", r["user_id"])

                                try:

                                    if jail_role and jail_role in member.roles:

                                        await member.remove_roles(jail_role, reason="Automatic unjail")

                                    if prev_roles:

                                        # filter roles by bot position

                                        good_roles = [rr for rr in prev_roles if rr and self._bot_role_position_ok(guild, rr)]

                                        if good_roles:

                                            await member.add_roles(*good_roles, reason="Automatic unjail")

                                    try:

                                        await member.send(f"Your jail time in {guild.name} has expired. You are now unjailed.")

                                    except Exception:

                                        pass

                                except Exception:

                                    logger.exception("Automatic unjail failed for %s in %s", member, guild)

                        # cleanup DB regardless of success

                        await self._run_db(self._remove_jailed_user_sync, r["guild_id"], r["user_id"])

            except Exception:

                logger.exception("check_timeouts loop failed")

    @check_timeouts.before_loop

    async def _before_check_timeouts(self):

        await self.bot.wait_until_ready()

    # ------------------ Appeal System ------------------

    @commands.Cog.listener()

    async def on_interaction(self, interaction: discord.Interaction):

        """Handle all appeal + ticket button interactions"""

        if not interaction.type == discord.InteractionType.component:

            return

        cid = interaction.data.get("custom_id")

        # --- CREATE APPEAL BUTTON ---

        if cid == "create_appeal":

            await self.handle_create_appeal(interaction)

            return

        # --- APPROVE BUTTON ---

        if cid == "ticket_approve":

            await self.handle_ticket_approve(interaction)

            return

        # --- DENY BUTTON ---

        if cid == "ticket_deny":

            await self.handle_ticket_deny(interaction)

            return

        # --- CLOSE TICKET BUTTON ---

        if cid == "ticket_close":

            await self.handle_ticket_close(interaction)

            return

    # ------------------ CREATE APPEAL ------------------

    async def handle_create_appeal(self, interaction: discord.Interaction):

        guild = interaction.guild

        user = interaction.user

        cfg = await self._run_db(self._get_guild_config_sync, guild.id)

        if not cfg:

            return await interaction.response.send_message("❌ Jail system not configured.", ephemeral=True)

        

        # check if user is jailed

        jailed = await self._run_db(self._get_jailed_user_sync, guild.id, user.id)

        if not jailed:

            return await interaction.response.send_message(

                "❌ You are not jailed.", ephemeral=True

            )

        

        # Check last appeals

        appeals = await self._run_db(self._get_appeals_for_user_sync, guild.id, user.id)

        if appeals:

            last = datetime.datetime.fromisoformat(appeals[0]["created_at"])

            diff = datetime.datetime.utcnow() - last

            if diff.total_seconds() < 86400:

                return await interaction.response.send_message(

                    "⏳ You can only create **one appeal every 24 hours**.",

                    ephemeral=True,

                )

        

        # Create ticket channel

        category = guild.get_channel(cfg.get("jail_category"))

        name = f"appeal-{user.name}".replace(" ", "-").lower()[:32]  # Limit to 32 chars

        

        # FIXED PERMISSIONS: Jail admins can see chat history and jailed user can see everything

        overwrites = {

            guild.default_role: discord.PermissionOverwrite(read_messages=False),

            user: discord.PermissionOverwrite(

                read_messages=True, 

                send_messages=True,

                read_message_history=True,  # FIX: Jailed can see chat history

                attach_files=True,

                embed_links=True

            ),

            guild.me: discord.PermissionOverwrite(

                read_messages=True, 

                send_messages=True,

                manage_messages=True,

                read_message_history=True

            ),

        }

        

        # Add jail admin role permissions

        admin_role = guild.get_role(cfg.get("admin_role")) if cfg.get("admin_role") else None

        if admin_role:

            overwrites[admin_role] = discord.PermissionOverwrite(

                read_messages=True, 

                send_messages=True,

                manage_messages=True,

                read_message_history=True  # FIX: Admins can see chat history

            )

        

        # Also add server administrators

        for role in guild.roles:

            if role.permissions.administrator:

                overwrites[role] = discord.PermissionOverwrite(

                    read_messages=True, 

                    send_messages=True,

                    manage_messages=True,

                    read_message_history=True

                )

        

        channel = await guild.create_text_channel(name=name, category=category, overwrites=overwrites)

        

        # Save appeal in DB

        appeal_id = await self._run_db(

            self._create_appeal_sync,

            guild.id,

            channel.id,

            user.id,

            jailed["reason"],  # Use the actual jail reason

        )

        self.ticket_channel_cache.add(channel.id)

        

        # FIXED: Create better embed with jail reason

        embed = discord.Embed(

            title="📩 Jail Appeal",

            description=f"Appeal for {user.mention} (`{user.id}`)",

            color=discord.Color.blurple(),

            timestamp=datetime.datetime.utcnow(),

        )

        embed.add_field(name="🔒 Original Jail Reason", value=jailed["reason"] or "No reason provided", inline=False)

        embed.add_field(name="📝 Instructions", value="Please explain why you should be unjailed. Staff will review your appeal.", inline=False)

        embed.set_footer(text=f"Appeal ID: {appeal_id} • Created at")

        

        # FIXED: Mention both admin role and user

        mention_text = []

        if admin_role:

            mention_text.append(admin_role.mention)

        mention_text.append(user.mention)

        

        await channel.send(

            content=" ".join(mention_text),

            embed=embed,

            view=TicketActionView(self)

        )

        

        await interaction.response.send_message(

            f"✅ Appeal created: {channel.mention}",

            ephemeral=True

        )

    # ------------------ BUTTON: APPROVE ------------------

    async def handle_ticket_approve(self, interaction: discord.Interaction):

        if not self._is_jail_admin(interaction.user):

            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        

        await interaction.response.defer()

        channel = interaction.channel

        guild = channel.guild

        

        # Find which user owns this appeal

        def find_appeal(conn):

            c = conn.cursor()

            row = c.execute(

                "SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'",

                (channel.id,)

            ).fetchone()

            return dict(row) if row else None

        

        appeal = await self._run_db(find_appeal)

        if not appeal:

            return await interaction.followup.send("❌ Appeal not found.")

        

        user = guild.get_member(appeal["user_id"])

        if not user:

            return await interaction.followup.send("❌ User not found in server.")

        

        # Unjail the user

        try:

            # Get jail config

            cfg = await self._run_db(self._get_guild_config_sync, guild.id)

            jail_role = guild.get_role(cfg["jail_role"]) if cfg else None

            

            # Get jailed user data

            jailed = await self._run_db(self._get_jailed_user_sync, guild.id, user.id)

            

            if jailed:

                # Remove jail role

                if jail_role and jail_role in user.roles:

                    await user.remove_roles(jail_role, reason=f"Appeal approved by {interaction.user}")

                

                # Restore previous roles

                if jailed.get("previous_roles"):

                    try:

                        prev_roles = [guild.get_role(rid) for rid in json.loads(jailed["previous_roles"]) if guild.get_role(rid) and self._bot_role_position_ok(guild, guild.get_role(rid))]

                        if prev_roles:

                            await user.add_roles(*prev_roles, reason=f"Appeal approved by {interaction.user}")

                    except Exception as e:

                        logger.error(f"Failed to restore some roles: {e}")

                

                # Remove from DB

                await self._run_db(self._remove_jailed_user_sync, guild.id, user.id)

            

            # Notify user

            try:

                await user.send(f"✅ Your appeal in {guild.name} has been **approved** by {interaction.user.mention}. You have been unjailed.")

            except Exception:

                pass

                

        except Exception as e:

            logger.exception("Appeal approval failed")

            return await interaction.followup.send(f"❌ Error during unjail: {e}")

        

        # Close appeal in DB

        transcript_file = await self._make_transcript_file(channel, user.id, appeal["id"])

        try:

            with open(transcript_file, "r", encoding="utf-8") as f:

                transcript_text = f.read()

        except Exception:

            transcript_text = "Failed to generate transcript"

        

        await self._run_db(self._close_appeal_sync, channel.id, "approved", transcript_text)

        

        # Clean up file

        try:

            os.remove(transcript_file)

        except Exception:

            pass

        

        await channel.send("✅ Appeal approved. Closing ticket in 5 seconds...")

        await asyncio.sleep(5)

        try:

            await channel.delete()

        except Exception:

            logger.exception("Failed to delete appeal channel %s", channel.id)

    # ------------------ BUTTON: DENY ------------------

    async def handle_ticket_deny(self, interaction: discord.Interaction):

        if not self._is_jail_admin(interaction.user):

            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        

        await interaction.response.defer()

        channel = interaction.channel

        guild = channel.guild

        

        # Find appeal

        def find_appeal(conn):

            c = conn.cursor()

            row = c.execute(

                "SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'",

                (channel.id,)

            ).fetchone()

            return dict(row) if row else None

        

        appeal = await self._run_db(find_appeal)

        if not appeal:

            return await interaction.followup.send("❌ Appeal not found.")

        

        user = guild.get_member(appeal["user_id"])

        if user:

            try:

                await user.send(f"❌ Your appeal in {guild.name} has been **denied** by {interaction.user.mention}.")

            except Exception:

                pass

        

        # Generate transcript and close appeal

        transcript_file = await self._make_transcript_file(channel, appeal["user_id"], appeal["id"])

        try:

            with open(transcript_file, "r", encoding="utf-8") as f:

                transcript_text = f.read()

        except Exception:

            transcript_text = "Failed to generate transcript"

        

        await self._run_db(self._close_appeal_sync, channel.id, "denied", transcript_text)

        

        # Clean up file

        try:

            os.remove(transcript_file)

        except Exception:

            pass

        

        await channel.send("❌ Appeal denied. Closing ticket in 5 seconds...")

        await asyncio.sleep(5)

        try:

            await channel.delete()

        except Exception:

            logger.exception("Failed to delete appeal channel %s", channel.id)

    # ------------------ BUTTON: CLOSE ------------------

    async def handle_ticket_close(self, interaction: discord.Interaction):

        if not self._is_jail_admin(interaction.user):

            return await interaction.response.send_message("❌ No permission.", ephemeral=True)

        

        await interaction.response.defer()

        channel = interaction.channel

        

        # Find appeal

        def find_appeal(conn):

            c = conn.cursor()

            row = c.execute(

                "SELECT * FROM appeals WHERE ticket_channel_id = ? AND status = 'open'",

                (channel.id,)

            ).fetchone()

            return dict(row) if row else None

        

        appeal = await self._run_db(find_appeal)

        if appeal:

            # Generate transcript and close appeal

            transcript_file = await self._make_transcript_file(channel, appeal["user_id"], appeal["id"])

            try:

                with open(transcript_file, "r", encoding="utf-8") as f:

                    transcript_text = f.read()

            except Exception:

                transcript_text = "Failed to generate transcript"

            

            await self._run_db(self._close_appeal_sync, channel.id, "closed", transcript_text)

            

            # Clean up file

            try:

                os.remove(transcript_file)

            except Exception:

                pass

        

        await channel.send("🔒 Ticket closed by staff. This channel will delete in 5 seconds.")

        await asyncio.sleep(5)

        try:

            await channel.delete()

        except Exception:

            logger.exception("Failed to delete appeal channel %s", channel.id)

    # ------------------ COMMAND: .accept ------------------

    @commands.command()

    async def accept(self, ctx):

        """Approve the appeal from inside the ticket."""

        if not self._is_jail_admin(ctx.author):

            return await ctx.send("❌ No permission.")

        

        # Create a minimal interaction-like object

        class MockInteraction:

            def __init__(self, ctx):

                self.user = ctx.author

                self.channel = ctx.channel

                self.guild = ctx.guild

                self.response = MockResponse()

            

            async def response_send_message(self, *args, **kwargs):

                return await ctx.send(*args, **kwargs)

        

        class MockResponse:

            async def send_message(self, *args, **kwargs):

                return await ctx.send(*args, **kwargs)

            async def defer(self):

                pass

        

        mock_interaction = MockInteraction(ctx)

        await self.handle_ticket_approve(mock_interaction)

    # ------------------ COMMAND: .deny ------------------

    @commands.command()

    async def deny(self, ctx):

        """Deny the appeal from inside the ticket."""

        if not self._is_jail_admin(ctx.author):

            return await ctx.send("❌ No permission.")

        

        class MockInteraction:

            def __init__(self, ctx):

                self.user = ctx.author

                self.channel = ctx.channel

                self.guild = ctx.guild

                self.response = MockResponse()

            

            async def response_send_message(self, *args, **kwargs):

                return await ctx.send(*args, **kwargs)

        

        class MockResponse:

            async def send_message(self, *args, **kwargs):

                return await ctx.send(*args, **kwargs)

            async def defer(self):

                pass

        

        mock_interaction = MockInteraction(ctx)

        await self.handle_ticket_deny(mock_interaction)

async def setup(bot: commands.Bot):

    await bot.add_cog(JailCog(bot))