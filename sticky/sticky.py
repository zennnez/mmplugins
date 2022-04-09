import discord
import asyncio
import calendar
import time
from discord.ext import commands
from typing import Optional
from core import checks
from core.models import PermissionLevel

class Sticky(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.plugin_db.get_partition(self)
        self.allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)

    async def check_msg(self, channel: discord.TextChannel, msg: discord.Message):
        my_perms: discord.Permissions = channel.permissions_for(msg.guild.me)

        if msg.content:
            content = msg.content
        else:
            content = ""

        if len(msg.attachments) > 0:
            attachment = msg.attachments[0]
        else:
            attachment = ""

        if my_perms.manage_webhooks:
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name=self.bot.user.name, user=self.bot.user)
            if webhook is None:
                webhook = await channel.create_webhook(name=self.bot.user.name)
            if msg.embeds:
                e = msg.embeds[0]
                msg2 = await webhook.send(
                    content,
                    files=attachment,
                    embed=e,
                    avatar_url=msg.author.display_avatar.url,
                    username=msg.author.display_name,
                    allowed_mentions=self.allowed_mentions,
                    wait=True,
                )
            else:
                msg2 = await webhook.send(
                    content,
                    files=attachment,
                    avatar_url=msg.author.display_avatar.url,
                    username=msg.author.display_name,
                    allowed_mentions=self.allowed_mentions,
                    wait=True,
                )
        else:
            if msg.embeds:
                e = msg.embeds[0]
                msg2: discord.Message = await channel.send(f"{attachment}{content}", embed=e)
            else:
                msg2: discord.Message = await channel.send(f"{attachment}{content}")

        return msg2

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not isinstance(message.channel, discord.TextChannel):
            return

        if message.type != discord.MessageType.default:
            return

        if message.author.id == self.bot.user.id:
            return

        if message.author.bot:
            return

        if len(message.clean_content) == 0:
            return

        channel = message.channel

        data = await self.db.find_one({'guild_id':message.guild.id, 'channel_id':channel.id})

        if not data:
            return

        if data['enabled'] is False:
            return

        data = self.db.find({'guild_id':message.guild.id, 'channel_id':channel.id})
        async for sticky in data:
            if sticky['counter'] >= (sticky['max_counter']-1):
                if (calendar.timegm(time.gmtime()) - sticky['msg_time']) > sticky['cooldown']:
                    try:
                        msg_check = await channel.fetch_message(sticky['msg_id'])
                        await msg_check.delete()

                    except discord.HTTPException:
                        await self.db.delete_one({'guild_id':message.guild.id, 'channel_id':channel.id, 'msg_id':sticky['msg_id']})
                        await self.bot.log_channel.send(f"Sticky msg failed in {channel.mention}")
            
                    except discord.NotFound:
                        await self.db.delete_one({'guild_id':message.guild.id, 'channel_id':channel.id, 'msg_id':sticky['msg_id']})
                        await self.bot.log_channel.send(f"Sticky msg not found in {channel.mention}")
            else:
                await self.db.update_many({'guild_id':message.guild.id, 'channel_id':channel.id}, {"$set":{'counter':sticky['counter']+1}})

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.raw_models.RawMessageDeleteEvent):
        channel = self.bot.get_channel(payload.channel_id)
        data = await self.db.find_one({'guild_id':payload.guild_id, 'channel_id':channel.id, 'msg_id':payload.message_id})

        if not data:
            return

        try:
            msg_check = (payload.cached_message if payload.cached_message else await channel.fetch_message(payload.message_id))
        except discord.NotFound:
            await self.db.delete_one({'guild_id':payload.guild_id, 'channel_id':channel.id, 'msg_id':payload.message_id})
            return await self.bot.log_channel.send(f"Could not find deleted sticky message in {channel.mention}")
        except discord.Forbidden:
            await self.db.delete_one({'guild_id':payload.guild_id, 'channel_id':channel.id, 'msg_id':payload.message_id})
            return await self.bot.log_channel.send(f"Failed to fetch deleted message due to permissions issue")

        msg: discord.Message = await self.check_msg(channel, msg_check)

        await self.db.find_one_and_update({'guild_id':payload.guild_id, 'channel_id':channel.id, 'msg_id':payload.message_id}, {"$set":{'msg_id':msg.id, 'counter':0, 'msg_time':calendar.timegm(time.gmtime())}})

    @commands.group(name="stick", usage="<option>", invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.MOD)
    async def stick_(self, ctx: commands.Context, max_counter: int, cooldown: Optional[int] = 30):
        """
        Stick a message to a channel

        **Usage:**
        Reply to a message: `{prefix}stick`
        """
        if ctx.author == self.bot.user:
            return
        if ctx.author.bot:
            return
        if not ctx.invoked_subcommand:
            def check(msg: discord.Message):
                return ctx.author == msg.author and ctx.channel == msg.channel
            embed = discord.Embed(timestamp=ctx.message.created_at, color=self.bot.main_color)
            try:
                if ctx.message.reference:
                    msg_check = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    if not (msg_check and isinstance(msg_check, discord.Message)):
                        return
                    msg = await self.check_msg(ctx.channel, msg_check)
                    await self.db.insert_one({
                        'guild_id':ctx.guild.id,
                        'msg_id':msg.id,
                        'channel_id':ctx.channel.id,
                        'counter':0,
                        'max_counter':max_counter,
                        'msg_time': calendar.timegm(time.gmtime()),
                        'cooldown': cooldown,
                        'enabled':True,
                    })
                    await ctx.send(embed=discord.Embed(color=self.bot.main_color, description=f"[Sticky Message]({msg.jump_url}) in {ctx.channel.mention}"), delete_after=20)

            except commands.BadArgument:
                await ctx.send_help(ctx.command)

    @stick_.command(name="list")
    @checks.has_permissions(PermissionLevel.MOD)
    async def stick_list(self, ctx):
        """
        Sends list of all channels-jump links
        """
        if ctx.author == self.bot.user:
            return
        if ctx.author.bot:
            return
        embed = discord.Embed(title="Sticky messages", color=self.bot.main_color)

        desc = ""
        embed.description = "No sticky message"
        data = self.db.find({'guild_id':ctx.guild.id})
        async for sticky in data:
            channel: discord.Channel = ctx.guild.get_channel(sticky['channel_id'])
            msg: discord.Message = await channel.fetch_message(sticky['msg_id'])
            desc += f"{channel.mention}: [Message]({msg.jump_url})\n"

        if desc != "":
            embed.description = desc

        await ctx.send(embed=embed)

    @stick_.command(name="toggle")
    @checks.has_permissions(PermissionLevel.MOD)
    async def stick_toggle(self, ctx: commands.Context, on_off: Optional[bool], channel: discord.TextChannel = None):
        """
        Toggle Sticky on/off.

        If `on/off` is not provided, the state will be flipped.
        **Usage:**
        To toggle for 1 sticky: (reply to the sticky message) `{prefix}stick toggle`
        To toggle for whole channel: `{prefix}stick toggle on/off <channel>`
        """
        if ctx.author == self.bot.user:
            return
        if ctx.author.bot:
            return

        try:
            if not channel and ctx.message.reference:
                msg = ctx.message.reference.message_id
                if data:= await self.db.find_one({'guild_id':ctx.guild.id, 'msg_id':msg}):
                    await self.db.find_one_and_update({'guild_id':ctx.guild.id, 'msg_id':msg}, {"$set":{'enabled':not data['enabled']}})
                    description = f"{'Enabled' if not data['enabled'] else 'Disabled'}"
            elif channel:
                if data:= self.db.find_one({'guild_id':ctx.guild.id, 'channel_id':channel.id}):
                    await self.db.update_many({'guild_id':ctx.guild.id, 'channel_id':channel.id}, {"$set":{'enabled':on_off}})
                    description = f"{'Enabled' if on_off else 'Disabled'}"
            else:
                return await ctx.send_help(ctx.command)

            await ctx.send(embed=discord.Embed(description=description, color=self.bot.main_color), delete_after=20)

        except commands.BadArgument:
            await ctx.send_help(ctx.command)

    @commands.command(name="unstick")
    @checks.has_permissions(PermissionLevel.MOD)
    async def unstick(self, ctx: commands.Context, channel: discord.TextChannel = None):
        """
        Unstick a message in a channel

        **Usage:**
        To clear 1 sticky: (reply to the sticky message) `{prefix}unstick`
        To clear all sticky in 1 channel: `{prefix}unstick <channel>`
        """
        if ctx.author == self.bot.user:
            return

        if ctx.author.bot:
            return

        try:
            if channel:
                await self.db.delete_many({'guild_id':ctx.guild.id, 'channel_id':channel.id})
            elif ctx.message.reference:
                msg = ctx.message.reference.message_id
                await self.db.delete_one({'guild_id':ctx.guild.id, 'msg_id':msg})
            else:
                return await ctx.send_help(ctx.command)

            await ctx.send(embed=discord.Embed(description="Cleared", color=self.bot.main_color), delete_after=20)

        except commands.BadArgument:
            await ctx.send_help(ctx.command)

def setup(bot):
    bot.add_cog(Sticky(bot))