# based on top-supporters plugins by Coolguy3289 (github)
# created for gothikit
from collections import defaultdict
import datetime

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel
from core.time import UserFriendlyTime

class AutoTopSupporters(commands.Cog):
    """Auto updated top supported in an embed message"""
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)
        self.config = None
        self.guild = self.bot.modmail_guild
        self.channel = None
        self.msg = None
        self.date = None

    async def cog_load(self):
        data = {
            "channel": None,
            "msg": None,
            "date": None,
            }

        self.config = await self.db.find_one({"_id": "config"})
        if self.config is None:
            await self.db.find_one_and_update({"_id": "config"}, {"$set": data}, upsert=True)

            self.config = await self.db.find_one({"_id": "config"})

        for k, v in data.items(): #remove once all data keys are defined
            if k not in self.config:
                self.config[k] = v
            
        if (self.config.get("channel", None) or self.config.get("msg", None) or self.config.get("date", None)) is None:
            return

        self.channel = self.guild.get_channel(int(self.config.get("channel", None))) or await self.guild.fetch_channel(int(self.config.get("channel", None)))
        self.msg = await self.channel.fetch_message(int(self.config.get("msg", None)))
        self.date = self.config.get("date", None)

    async def _update_config(self):
        await self.db.find_one_and_update({"_id": "config"},
            {"$set": {
                "channel": self.channel.id if self.channel else None,
                "msg": self.msg.id if self.msg else None,
                "date": self.date,
                },
            }, upsert=True)


    async def update_supporters(self):
        if not (self.date or self.msg or self.channel):
            return

        date = datetime.datetime.fromtimestamp(self.date).astimezone(datetime.timezone.utc)

        logs = await self.bot.api.logs.find({"open": False}).to_list(None)
        logs = filter(lambda x: isinstance(x['closed_at'], str) and datetime.datetime.fromisoformat(x['closed_at']).astimezone(datetime.timezone.utc) > date, logs)

        supporters = defaultdict(int)

        for l in logs:
            supporters_involved = set()
            for x in l['messages']:
                if x.get('type') in ('anonymous', 'thread_message') and x['author']['mod']:
                    supporters_involved.add(x['author']['id'])
            for s in supporters_involved:
                supporters[s] += 1

        supporters_keys = sorted(supporters.keys(), key=lambda x: supporters[x], reverse=True)

        fmt = ''

        n = 1
        for k in supporters_keys:
            u = self.bot.get_user(int(k))
            if u:
                fmt += f'**{n}.** `{u}` - {supporters[k]}\n'
                n += 1

        embed = discord.Embed(title='Active Supporters', description=fmt, timestamp=date, color=self.bot.main_color)
        embed.set_footer(text='Since')
        await self.msg.edit(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.type != discord.MessageType.default:
            return

        thread = None
        recipient = message.author
        ctx = await self.bot.get_context(message)

        if ctx.valid and ctx.command and ctx.command.qualified_name != "claim":
            return

        claim_cog = self.bot.get_cog('ClaimThread')
        if not await claim_cog.check_claimer(ctx, ctx.author.id):
            return

        await self.update_supporters()

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        await self.update_supporters()

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.update_supporters()

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.group(name='tops', invoke_without_command=True)
    async def tops_(self, ctx):
        """Top Supporter settings"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @tops_.command(name='channel')
    async def tops_channel(self, ctx, channel: discord.TextChannel = None):
        """Set status embed channel"""
        if channel:
            embed = discord.Embed(title="Active Supporters", color=self.bot.main_color, description="No records yet")
            msg = await channel.send(embed=embed)
            await msg.pin()

            self.channel = channel
            self.msg = msg
            self.embed = msg.embeds[0]
            await self._update_config()
            await ctx.reply(f"Channel {channel.mention} is set.")
            if self.date:
                await self.update_supporters()
        else:
            await self.msg.delete()
            self.channel = None
            self.msg = None
            self.embed = None
            await self._update_config()

            await ctx.reply("Disabled status embed message.")

    @checks.has_permissions(PermissionLevel.ADMIN)
    @tops_.command(name='time')
    async def tops_time(self, ctx, *, time: UserFriendlyTime):
        """
        Sets time period

        Examples for time:
        `15d`, `10m`, `10m30s`, `1h`, `1y1mo2w5d10h30m15s`
        """
        time = discord.utils.utcnow() - (time.dt - discord.utils.utcnow())
        self.date = time.timestamp()

        exact_time_timestamp = f"<t:{int(self.date)}:f>"
        relative_timestamp = f"<t:{int(self.date)}:R>"
        response = f"Time set to **{exact_time_timestamp}** -{relative_timestamp}."

        await self._update_config()
        await ctx.send(response)

        if self.channel:
            await self.update_supporters()

async def setup(bot):
    await bot.add_cog(AutoTopSupporters(bot))
