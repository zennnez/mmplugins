## created for retdstoneherlive (discord)
import discord
from discord.ext import commands
import asyncio
import os

MUSIC_FOLDER = os.path.join(os.path.dirname(__file__), "waiting_music")

class WaitingRoom(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)

        self.config = None

        self.voice_channel_id = None
        self.notif_channel_id = None
        self.ping_role_id = None

        self.voice_channel = None
        self.notif_channel = None
        self.ping_role = None

        self.enabled = None
        self.music_file = None

        self.voice_client = None
        self.playing_task = None

        if not os.path.exists(MUSIC_FOLDER):
            os.makedirs(MUSIC_FOLDER)

    async def cog_load(self):
        data = {
            "voice_channel_id": None,
            "notif_channel_id": None,
            "ping_role_id": None,
            "enabled": True,
            "music_file": None,
        }

        self.config = await self.db.find_one({"_id": "config"})
        if self.config is None:
            await self.db.find_one_and_update({"_id": "config"}, {"$set": data}, upsert=True)

            self.config = await self.db.find_one({"_id": "config"})

        for k, v in data.items():
            if k not in self.config:
                self.config[k] = v

        self.voice_channel_id = self.config.get("voice_channel_id", int())
        self.notif_channel_id = self.config.get("notif_channel_id", int())
        self.ping_role_id = self.config.get("ping_role_id", int())
        self.enabled = self.config.get("enabled", bool())
        self.music_file = self.config.get("music_file", str())

    async def _update_config(self):
        await self.db.find_one_and_update({"_id": "config"},
            {"$set": {
                "voice_channel_id": self.voice_channel_id,
                "notif_channel_id": self.notif_channel_id,
                "ping_role_id": self.ping_role_id,
                "enabled": self.enabled,
                "music_file": self.music_file,
                }
            }, upsert=True)

    #
    # ========== COMMAND GROUP ==========
    #

    @commands.group(
        name="waiting",
        description="Configure the waiting room system.",
        invoke_without_command=True
    )
    async def waiting(self, ctx: commands.Context):
        """
        Configure the waiting room system.
        Use this command to manage the waiting room settings, such as enabling/disabling the system,
        setting notification channels, and configuring the waiting room voice channel.
        """
        await ctx.send_help(ctx.command)

    # Subgroup: waiting set
    @waiting.group(
        name="set",
        description="Change waiting room settings.",
        invoke_without_command=True
    )
    async def waiting_set(self, ctx: commands.Context):
        """
        Change waiting room settings.
        This command allows you to modify specific settings of the waiting room system, such as
        the ping role, notification channel, and voice channel.
        """
        await ctx.send_help(ctx.command)

    #
    # ========== VIEW SETTINGS ==========
    #

    @waiting.command(name="view", description="View current waiting room settings.")
    async def view_settings(self, ctx: commands.Context):
        """
        View current waiting room settings.
        Displays the current configuration of the waiting room system, including whether it is enabled,
        the notification channel, ping role, voice channel, and the music file being used.
        """
        embed = discord.Embed(title="🎧 Waiting Room Settings", color=discord.Color.blurple())

        embed.add_field(
            name="Enabled",
            value=str(self.enabled),
            inline=False
        )

        embed.add_field(
            name="Notification Channel",
            value=f"<#{self.notif_channel_id}>" if self.notif_channel_id else "`Not set`",
            inline=False
        )

        embed.add_field(
            name="Ping Role",
            value=f"<@&{self.ping_role_id}>" if self.ping_role_id else "`Not set`",
            inline=False
        )

        embed.add_field(
            name="Voice Channel",
            value=f"<#{self.voice_channel_id}>" if self.voice_channel_id else "`Not set`",
            inline=False
        )

        embed.add_field(
            name="Music File",
            value=self.music_file if self.music_file else "`Not set`",
            inline=False
        )

        await ctx.send(embed=embed)

    #
    # ========== SET PING ROLE ==========
    #

    @waiting_set.command(name="ping_role", description="Set the role to ping when someone joins the waiting room.")
    async def set_ping_role(self, ctx: commands.Context, role: discord.Role):
        """
        Set the role to ping when someone joins the waiting room.
        Specify a role that will be notified whenever a user joins the waiting room voice channel.
        """
        self.ping_role_id = role.id
        await self._update_config()
        await ctx.send(f"✅ Ping role set to {role.mention}")

    #
    # ========== ENABLE / DISABLE PLUGIN ==========
    #

    @waiting_set.command(name="enabled", description="Enable or disable the waiting room system.")
    async def set_enabled(self, ctx: commands.Context, state: bool):
        """
        Enable or disable the waiting room system.
        Use this command to turn the waiting room system on or off.
        """
        self.enabled = state
        await self._update_config()
        await ctx.send(f"✅ Waiting room {'enabled' if state else 'disabled'}.")

    #
    # ========== SET NOTIFICATION CHANNEL ==========
    #

    @waiting_set.command(name="notif_channel", description="Set the channel where notifications will be sent.")
    async def set_notif_channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Set the channel where notifications will be sent.
        Specify the text channel where notifications about users joining the waiting room will be sent.
        """
        self.notif_channel_id = channel.id
        await self._update_config()
        await ctx.send(f"✅ Notifications will be sent in {channel.mention}")

    #
    # ========== SET VOICE CHANNEL ==========
    #

    @waiting_set.command(name="voice_channel", description="Set the waiting room voice channel.")
    async def set_voice_channel(self, ctx: commands.Context, channel: discord.VoiceChannel):
        """
        Set the waiting room voice channel.
        Specify the voice channel that will be used as the waiting room.
        """
        self.voice_channel_id = channel.id
        await self._update_config()
        await ctx.send(f"✅ Waiting room voice channel set to **{channel.name}**")

    #
    # ========== SET MUSIC (UPLOAD FILE) ==========
    #

    @waiting_set.command(name="music", description="Upload an MP3 file to use as waiting room music.")
    async def set_music(self, ctx: commands.Context, file: discord.Attachment):
        """
        Upload an MP3 file to use as waiting room music.
        Upload a music file that will be played in the waiting room voice channel.
        Only MP3 files are supported.
        """
        if not file.filename.lower().endswith(".mp3"):
            await ctx.send("❌ Only MP3 files are allowed.")
            return

        save_path = os.path.join(MUSIC_FOLDER, file.filename)
        await file.save(save_path)

        self.music_file = save_path
        await self._update_config()

        await ctx.send(f"🎵 Music updated.\nSaved as: `{file.filename}`")

    #
    # ========== VOICE AUTO JOIN LOGIC ==========
    #

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        if not self.enabled:
            return

        # Only trigger when user joins the *configured* waiting room
        if (
            before.channel is None
            and after.channel
            and self.voice_channel_id
            and after.channel.id == self.voice_channel_id
        ):

            # If bot's waiting room is not configured
            if not self.music_file:
                return

            # Notify
            self.notif_channel = self.bot.get_channel(self.notif_channel_id)
            ping_role_id = self.ping_role_id
            ping_mention = f"<@&{ping_role_id}>" if ping_role_id else ""

            if self.notif_channel:
                await self.notif_channel.send(
                    f"🔔 {ping_mention} **{member.display_name}** joined **{after.channel.name}** and needs help!"
                )

            # Connect if not already connected
            if not self.voice_client or not self.voice_client.is_connected():
                self.voice_client = await after.channel.connect()

                # Play music
                source = discord.FFmpegPCMAudio(self.music_file, executable="ffmpeg")
                self.voice_client.play(source)

        # Check if the bot should disconnect
        if (
            before.channel
            and before.channel.id == self.voice_channel_id
            and len(before.channel.members) <= 1
        ):
            if self.voice_client and self.voice_client.is_connected():
                await self.voice_client.disconnect(force=True)
                self.voice_client = None


async def setup(bot):
    await bot.add_cog(WaitingRoom(bot))
