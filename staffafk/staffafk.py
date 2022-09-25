import discord
import datetime

from discord.ext import commands, tasks
from typing import Union
from pytz import timezone

from core import checks
from core.models import PermissionLevel

class StaffAFK(commands.Cog):  
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.task = self.staffafk_background_task.start()

    def cog_unload(self):
        self.task.cancel()

    async def mention(self, ctx, user_or_role):
        if (len(user_or_role) == 1 and isinstance(user_or_role[0], str) and user_or_role[0].lower() in ("disable")):
            if user_or_role[0].lower() == "disable":
                mention = None
        else:
            mention = []
            pings = ("all", "everyone", "here")
            for m in user_or_role:
                if not isinstance(m, (discord.Role, discord.Member)) and m not in pings:
                    continue
                elif m == ctx.guild.default_role or m in ("all", "everyone"):
                    mention.append("@everyone")
                    continue
                elif m == "here":
                    mention.append("@here")
                    continue
                mention.append(m.mention)

            mention = " ".join(mention)

        return mention

    @checks.has_permissions(PermissionLevel.MOD)
    @commands.group(invoke_without_command=True)
    async def staffafk(self, ctx):
        """
        Base command for Staff-Afk. Sends Help message.
        """
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.MOD)
    @staffafk.group(name='settings')
    async def staffafk_settings(self, ctx):
        """
        Check or set the Staff-Afk Settings.
        """
        if not ctx.invoked_subcommand:
            config = await self.db.find_one({"_id": "config"})
            if not config:
                return await ctx.send_help(ctx.command)

            embed = discord.Embed(color=self.bot.main_color)
            embed.title = 'Staff Afk Settings'
            embed.add_field(name='Online Message', value=config['upmsg'], inline=False)
            embed.add_field(name='Afk Message', value=config['afkmsg'], inline=False)
            embed.add_field(name='Online Ping', value=config['upping'], inline=False)
            embed.add_field(name='Afk Ping', value=config['afkping'], inline=False)
            embed.add_field(name='Auto Change Status', value='Enabled' if config['auto_enabled'] else 'Disabled', inline=False)
            await ctx.send(embed=embed)

    @checks.has_permissions(PermissionLevel.MOD)
    @staffafk_settings.command(name='upping')
    async def staffafk_settings_upping(self, ctx, *roles: Union[discord.Role, discord.Member, str]):
        """
        The role to ping when Staff is Online.
        """
        mention = await self.mention(ctx, roles)
        await self.db.find_one_and_update({"_id": "config"}, {"$set": {"upping": mention}}, upsert=True)
        await ctx.send(embed=await self.generate_embed(self, f'Set the Online ping to:\n{mention}'))

    @checks.has_permissions(PermissionLevel.MOD)
    @staffafk_settings.command(name='afkping')
    async def staffafk_settings_afkping(self, ctx, *roles: Union[discord.Role, discord.Member, str]):
        """
        The role to ping when Staff is AFK/Offline.
        """
        mention = await self.mention(ctx, roles)
        await self.db.find_one_and_update({"_id": "config"}, {"$set": {"afkping": mention}}, upsert=True)
        await ctx.send(embed=await self.generate_embed(self, f'Set the AFK ping to:\n{mention}'))

    @checks.has_permissions(PermissionLevel.MOD)
    @staffafk_settings.command(name='upmsg')
    async def staffafk_settings_upmsg(self, ctx, *, upmsg: str):
        """
        Set the Staff Online Message.
        """
        await self.db.find_one_and_update({"_id": "config"}, {"$set": {"upmsg": upmsg}}, upsert=True)
        await ctx.send(embed=await self.generate_embed(self, f'Set the Online message to:\n{upmsg}'))

    @checks.has_permissions(PermissionLevel.MOD)
    @staffafk_settings.command(name='afkmsg')
    async def staffafk_settings_afkmsg(self, ctx, *, afkmsg: str):
        """
        Set the Staff is AFK/Offline Message.
        """
        await self.db.find_one_and_update({"_id": "config"}, {"$set": {"afkmsg": afkmsg}}, upsert=True)
        await ctx.send(embed=await self.generate_embed(self, f'Set the AFK message to:\n{afkmsg}'))

    @checks.has_permissions(PermissionLevel.MOD)
    @staffafk_settings.command(name='auto')
    async def staffafk_settings_auto_enabled(self, ctx):
        """
        Enable or Disable the auto change status feature.
        """
        config = await self.db.find_one({"_id": "config"})
        await self.db.find_one_and_update({"_id": "config"}, {"$set": {"auto_enabled": not config['auto_enabled']}}, upsert=True)
        await ctx.send(embed=await self.generate_embed(self, f"Set the status to:\n{'Enabled' if not config['auto_enabled'] else 'Disabled'}"))

    @checks.has_permissions(PermissionLevel.MOD)
    @staffafk.command(name='afk')
    async def staffafk_change_message(self, ctx, status: bool):
        """
        Manually change the Online/Offline status, instead of the set timer.
        """
        config = await self.db.find_one({"_id": "config"})
        if status:
            await self.change_message(config['afkmsg'])
            await self.change_ping(config['afkping'])
            await ctx.send(embed=await self.generate_embed(self, f"Changed the Ping to:\n{config['afkping']}\n\nChanged the Message to:\n{config['afkmsg']}"))
        else:
            await self.change_message(config['upmsg'])
            await self.change_ping(config['upping'])
            await ctx.send(embed=await self.generate_embed(self, f"Changed the Ping to:\n{config['upping']}\n\nChanged the Message to:\n{config['upmsg']}"))

    async def change_message(self, msg):
        await self.bot.config.set('thread_creation_response', msg)
        await self.bot.config.update()

    async def change_ping(self, ping):
        await self.bot.config.set('mention', ping)
        await self.bot.config.update()

    @tasks.loop(seconds=60)
    async def staffafk_background_task(self):
        config = await self.db.find_one({"_id": "config"})
        if not config:
            await self.db.find_one_and_update({"_id": "config"}, {"$set": {'upmsg': None, 'afkmsg': None, 'upping': None, 'afkping': None, 'auto_enabled': False}}, upsert=True)
            config = await self.db.find_one({"_id": "config"})

        if not config['auto_enabled']:
            return

        hours = int(datetime.datetime.now(timezone("America/New_York")).time().strftime("%H"))
        minutes = int(datetime.datetime.now(timezone("America/New_York")).time().strftime("%M"))
        if hours == 0:
            if minutes == 0:
                msg = ""

                if config['afkmsg'] is not None:
                    await self.change_message(config['afkmsg'])
                    msg += f"Changed the Message to:\n{config['afkmsg']}\n\n"

                if config['afkping'] is not None:
                    await self.change_ping(config['afkping'])
                    msg += f"Changed the Ping to:\n{config['afkping']}"

                if self.bot.log_channel and msg != "":
                    await self.bot.log_channel.send(embed=await self.generate_embed(self, msg))

        if hours == 6:
            if minutes == 0:
                msg = ""

                if config['upmsg'] is not None:
                    await self.change_message(config['upmsg'])
                    msg += f"Changed the Message to:\n{config['upmsg']}\n\n"

                if config['upping'] is not None:
                    await self.change_ping(config['upping'])
                    msg += f"Changed the Ping to:\n{config['upping']}"

                if self.bot.log_channel and msg != "":
                    await self.bot.log_channel.send(embed=await self.generate_embed(self, msg))

    @staffafk_background_task.before_loop
    async def before_staffafk(self):
        await self.bot.wait_until_ready()  

    @staticmethod
    async def generate_embed(self, description: str):
        embed = discord.Embed()
        embed.colour = self.bot.main_color
        embed.description = description

        return embed

async def setup(bot):
    await bot.add_cog(StaffAFK(bot))
