# created for TheArxOfTheNel#4007, Minion_Kadin#2022 and Sasiko#1234 (discord)
# updated with vc for gothikit

import asyncio
import discord
from discord.ext import commands, tasks
from datetime import datetime
from pytz import timezone
from core import checks
from core.models import DMDisabled, PermissionLevel

class TicketStats(commands.Cog):
    """Shows the current status of tickets"""
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)

        self.config = None
        self.guild = self.bot.modmail_guild

        self.stats_cat = None
        self.vc = False
        self.data = dict()
        self.tickets_backlog = int()
        self.tickets_open = int()
        self.tickets_24hrs = int()
        self.tickets_lifetime = int()
        self.daily_reset = bool()
        self.activity = bool()
        self.status_group = dict()
        self.status_msg = list()
        self.enabled = dict()

    async def dm_status(self):
        if self.bot.config["dm_disabled"] == DMDisabled.ALL_THREADS:
            if self.activity:
                await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"No Tickets"))
            return "All Tickets Disabled"
        elif self.bot.config["dm_disabled"] == DMDisabled.NEW_THREADS:
            if self.activity:
                await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"Open Tickets Only"), status=discord.Status.idle)
            return "New Tickets Disabled"
        elif self.tickets_open > self.tickets_backlog:
            if self.activity:
                await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"Delayed Responses"), status=discord.Status.dnd)
            return "Backlogged"
        else:
            if self.activity:
                await self.bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=f"Normal Responses"), status=discord.Status.online)
            return "Normal"

    async def nuke_channel(self, name):
        channel = discord.utils.find(lambda c: c.name.startswith(name), self.guild.channels)
        if isinstance(channel, discord.VoiceChannel) and channel.category == self.stats_cat:
            await channel.delete()
            await asyncio.sleep(1)

    async def get_cat(self):
        if not self.vc:
            return int()

        stats_cat = discord.utils.get(self.guild.categories, id=self.config.get("stats_cat", int()))
        if not stats_cat:
            stats_cat = await self.guild.create_category("Tickets Stats", overwrites={self.guild.default_role: discord.PermissionOverwrite(connect=False)}, reason='Ticket Stats Category')
            self.config['stats_cat'] = stats_cat.id
            await self._update_config()
            await stats_cat.edit(position=1)

        return stats_cat

    async def get_logs(self):
        logs = self.bot.db.logs
        opened = await logs.find({"open": True}).to_list(None)
        closed = await logs.find({"open": False}).to_list(None)

        return len(opened), len(closed)

    async def cog_load(self):
        data = {
            "stats_cat": int(),
            "backlog": 5,
            "open": int(),
            "24hrs": int(),
            "lifetime": int(),
            "daily_reset": True,
            "activity": False,
            "vc": False,
            "msg": dict(),
            "enabled": {
                "Status": True,
                "Open Tickets": True,
                "Resolved - Lifetime": True,
                "Resolved - Today": True,
            },
        }

        self.config = await self.db.find_one({"_id": "config"})
        if self.config is None:
            await self.db.find_one_and_update({"_id": "config"}, {"$set": data}, upsert=True)

            self.config = await self.db.find_one({"_id": "config"})

        for k, v in data.items():
            if k not in self.config:
                self.config[k] = v
            
        self.tickets_backlog = self.config.get("backlog", int())
        self.tickets_open = self.config.get("open", int())
        self.tickets_24hrs = self.config.get("24hrs", int())
        self.tickets_lifetime = self.config.get("lifetime", int())

        self.daily_reset = self.config.get("daily_reset", bool())
        self.activity = self.config.get("activity", bool())
        self.status_group = self.config.get("msg", dict())
        self.vc = self.config.get("vc", bool())
        self.stats_cat = await self.get_cat()
        self.enabled = self.config.get("enabled", dict())


        self.tickets_open, self.tickets_lifetime = await self.get_logs()

        self.data = {
            'Status': await self.dm_status(),
            'Open Tickets': self.tickets_open,
            'Resolved - Lifetime': self.tickets_lifetime,
            'Resolved - Today': self.tickets_24hrs,
        }

        await self.update_stats()
        self.reset_daily.start()

    async def _update_config(self):
        await self.db.find_one_and_update({"_id": "config"},
            {"$set": {
                "stats_cat": self.stats_cat.id if self.stats_cat else 0,
                "backlog": self.tickets_backlog,
                "open": self.tickets_open,
                "24hrs": self.tickets_24hrs,
                "lifetime": self.tickets_lifetime,
                "daily_reset": self.daily_reset,
                "activity": self.activity,
                "vc": self.vc,
                "msg": self.status_group,
                "enabled": self.enabled}
            }, upsert=True)

    def cog_unload(self):
        if self.reset_daily:
            self.reset_daily.cancel()

    async def update_stats(self, data = None):
        data = data or self.data
        data = {k:v for k,v in data.items() if self.enabled[k]}
        await self._update_config()

        if self.vc:
            for name, count in data.items():
                channel = discord.utils.find(lambda c: c.name.startswith(name), self.guild.channels)
                await asyncio.sleep(2)
                if channel is None or not isinstance(channel, discord.VoiceChannel):
                    await self.guild.create_voice_channel(name=f"{name}: {count}", category=self.stats_cat)
                    continue
                
                await channel.edit(name=f"{name}: {count}")
            
            if len(self.status_group) != 0:
                for k, v in self.status_group.items():
                    update_channel = self.bot.guild.get_channel(int(k)) or await self.bot.fetch_channel(int(k))
                    if update_channel and update_channel.category == self.stats_cat:
                        await update_channel.delete()
                        await asyncio.sleep(1)
                self.status_group = dict()
                await self._update_config()

        else:
            for name, count in data.items():
                await self.nuke_channel(name)

            if self.stats_cat:
                try:
                    await self.stats_cat.delete()
                except (discord.NotFound, AttributeError):
                    pass

            if len(self.status_msg) != 0 and self.status_msg[0].embeds and self.status_msg[0].embeds[0]:
                embed = self.status_msg[0].embeds[0]
                embed_dict = embed.to_dict()
                for name, count in data.items():
                    for field in embed_dict["fields"]:
                        if field['name'] == name:
                            field['value'] = count
                            break

                embed = discord.Embed.from_dict(embed_dict)
                for m in self.status_msg:
                    try:
                        await m.edit(embed=embed)
                        await asyncio.sleep(1)
                    except:
                        pass

            else:
                if len(self.status_group) == 0:
                    return f"Please use `{self.bot.prefix}ticketstats channel <yourchannel>` command to set stats channel/s."

                to_delete = []
                for k, v in self.status_group.items():
                    try:
                        update_channel = self.bot.guild.get_channel(int(k)) or await self.bot.fetch_channel(int(k))
                        if not update_channel:
                            to_delete.append(k)
                            continue

                        status_msg = await update_channel.fetch_message(int(v))
                        if status_msg:
                            embed = status_msg[0].embeds[0]
                            embed_dict = embed.to_dict()
                            for name, count in data.items():
                                for field in embed_dict["fields"]:
                                    if field['name'] == name:
                                        field['value'] = count
                                        break

                            embed = discord.Embed.from_dict(embed_dict)
                            await status_msg.edit(embed=embed)
                            await asyncio.sleep(1)
                            self.status_msg.append(status_msg)
                        else:
                            embed = discord.Embed(title='Tickets Statistics', color=self.bot.main_color)
                            for name, count in data.items():
                                embed.add_field(name=name, value=count, inline=False)
                            status_msg = await update_channel.send(embed=embed)
                            await asyncio.sleep(1)
                            self.status_msg.append(status_msg)
                            self.status_group[str(update_channel.id)] = status_msg.id
                            await self._update_config()
                    except:
                        pass

                if len(to_delete) != 0:
                    for k in to_delete:
                        del self.status_group[k]
                        await self._update_config()

    @commands.Cog.listener()
    async def on_command(self, ctx):
        if ctx.command.qualified_name in ['disable new', 'disable all', 'enable'] and await ctx.command.can_run(ctx):
            data = {
                'Status': await self.dm_status(),
            }
            await self.update_stats(data)

    async def check_before_update(self, channel):
        await asyncio.sleep(5)
        if channel.guild != self.guild or await self.bot.api.get_log(channel.id) is None:
            return False

        return True

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if await self.check_before_update(channel):
            self.tickets_open = self.tickets_open+1
            data = {
                'Status': await self.dm_status(),
                'Open Tickets': self.tickets_open,
            }
            await self.update_stats(data)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if await self.check_before_update(channel):
            self.tickets_open = self.tickets_open-1
            self.tickets_24hrs = self.tickets_24hrs+1
            self.tickets_lifetime = self.tickets_lifetime+1
            data = {
                'Status': await self.dm_status(),
                'Open Tickets': self.tickets_open,
                'Resolved - Lifetime': self.tickets_lifetime,
                'Resolved - Today': self.tickets_24hrs,
            }
            await self.update_stats(data)

    @tasks.loop(minutes=59)
    async def reset_daily(self):
        hours = int(datetime.now(timezone("Asia/Kolkata")).time().strftime("%H"))

        if hours == 0 and self.daily_reset:
            self.tickets_24hrs = 0

            data = {
                'Resolved - Today': '0',
            }
            await self.update_stats(data)

            self.daily_reset = False
            await self._update_config()

        if hours != 0 and not self.daily_reset:
            self.daily_reset = True
            await self._update_config()

    @reset_daily.before_loop
    async def before_reset_daily(self):
      await self.bot.wait_until_ready()  

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.group(name='ticketstats', invoke_without_command=True)
    async def ticketstats_(self, ctx):
        """Manually adjust the ticket status counter"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='open')
    async def ticketstats_open(self, ctx, counter: int):
        """Manually adjust the open tickets counter"""
        self.tickets_open = counter
        await self._update_config()
        data = {
            'Open Tickets': self.tickets_open,
        }
        await self.update_stats(data)
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='day')
    async def ticketstats_day(self, ctx, counter: int):
        """Manually adjust the day's tickets counter"""
        self.tickets_24hrs = counter
        await self._update_config()
        data = {
            'Resolved - Today': self.tickets_24hrs,
        }
        await self.update_stats(data)
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='lifetime')
    async def ticketstats_lifetime(self, ctx, counter: int):
        """Manually adjust the lifetime tickets counter"""
        self.tickets_lifetime = counter
        await self._update_config()
        data = {
            'Resolved - Lifetime': self.tickets_lifetime,
        }
        await self.update_stats(data)
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='backlog')
    async def ticketstats_backlog(self, ctx, counter: int):
        """Set the backlog limit"""
        self.tickets_backlog = counter
        await self._update_config()
        await self.update_stats()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='vc')
    async def ticketstats_vc(self, ctx, enable_disable: bool):
        """
        Set the stats type
        Set `True` for voice channels or set `False` for Stats Message
        """
        self.vc = enable_disable
        await self._update_config()
        await self.update_stats()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='activity')
    async def ticketstats_activity(self, ctx, status: bool):
        """
        Enable/Disable bot activity based on current status
        `{prefix}ticketstats activity yes/no`
        """
        self.activity = status
        await self._update_config()
        await self.dm_status()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='channel')
    async def ticketstats_channel(self, ctx, channel: discord.TextChannel):
        """Set More stats channels"""
        if str(channel.id) in self.status_group:
            try:
                status_msg = await channel.fetch_message(int(self.status_group[str(channel.id)]))
                await status_msg.delete()
            except (discord.NotFound, AttributeError):
                pass
            del self.status_group[str(channel.id)]
            status = f"Removed {channel.mention} from the list.\nTotal channels in the list: {len(self.status_group)}"
        else:
            self.status_group[str(channel.id)] = None
            status = f"Added {channel.mention} to the list.\nTotal channels in the list: {len(self.status_group)}"
            data = {k:v for k,v in self.data.items() if self.enabled[k]}
            embed = discord.Embed(title='Tickets Statistics', color=self.bot.main_color)
            for name, count in data.items():
                embed.add_field(name=name, value=count, inline=False)
            status_msg = await channel.send(embed=embed)
            await asyncio.sleep(1)
            self.status_msg.append(status_msg)
            self.status_group[str(channel.id)] = status_msg.id

        await self._update_config()
        await ctx.reply(status)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.group(name='enable', invoke_without_command=True)
    async def ticketstats_enable(self, ctx):
        """Select the stats you want to enable"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_enable.command(name='status')
    async def ticketstats_enable_status(self, ctx, status: bool):
        """Enable Tickets stats message"""
        name = "Status"
        self.enabled[name] = status
        await self._update_config()
        if not status:
            await self.nuke_channel(name)
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_enable.command(name='open')
    async def ticketstats_enable_open(self, ctx, status: bool):
        """Enable Open Tickets stats"""
        name = "Open Tickets"
        self.enabled[name] = status
        await self._update_config()
        if not status:
            await self.nuke_channel(name)
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_enable.command(name='lifetime')
    async def ticketstats_enable_lifetime(self, ctx, status: bool):
        """Enable Resolved - Lifetime stats"""
        name = "Resolved - Lifetime"
        self.enabled[name] = status
        await self._update_config()
        if not status:
            await self.nuke_channel(name)
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_enable.command(name='today')
    async def ticketstats_enable_today(self, ctx, status: bool):
        """Enable Resolved - Today stats"""
        name = "Resolved - Today"
        self.enabled[name] = status
        await self._update_config()
        if not status:
            await self.nuke_channel(name)
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstats_.command(name='restorecounter')
    async def ticketstats_restorecounter(self, ctx):
        """Reads the logs database and restores the __Open__ and __Lifetime Closed__ count from it"""

        self.tickets_open, self.tickets_lifetime = await self.get_logs()
        await self._update_config()
        data = {
            'Open Tickets': self.tickets_open,
            'Resolved - Lifetime': self.tickets_lifetime,
        }
        await self.update_stats(data)
        await ctx.message.add_reaction('✅')

async def setup(bot):
    await bot.add_cog(TicketStats(bot))