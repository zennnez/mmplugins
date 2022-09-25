import discord
import calendar
import time
from discord.ext import commands
from typing import Optional
from core import checks
from core.models import PermissionLevel

class Sticky(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.allowed_mentions = discord.AllowedMentions(users=True, roles=False, everyone=False)

    async def send_sticky(self, channel, author, content, embed, attachments):
        if not attachments:
            attachments = ""

        webhook = None
        my_perms: discord.Permissions = channel.permissions_for(channel.guild.me)
        if my_perms.manage_webhooks:
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name=self.bot.user.name, user=self.bot.user)
            if webhook is None:
                webhook = await channel.create_webhook(name=self.bot.user.name)


        if embed:
            if webhook:
                msg2 = await webhook.send(
                    content,
                    embed=embed,
                    files=attachments,
                    avatar_url=author.display_avatar.url,
                    username=author.display_name,
                    allowed_mentions=self.allowed_mentions,
                    wait=True,
                )
            else:
                msg2: discord.Message = await channel.send(content, embed=embed)

        else:
            if webhook:
                msg2 = await webhook.send(
                    content,
                    files=attachments,
                    avatar_url=author.display_avatar.url,
                    username=author.display_name,
                    allowed_mentions=self.allowed_mentions,
                    wait=True,
                )
            else:
                msg2: discord.Message = await channel.send(content)

        return msg2

    async def check_msg(self, channel: discord.TextChannel, msg: discord.Message, author):
        author = author or msg.author

        if msg.content:
            content = msg.content
        else:
            content = ""

        if len(msg.attachments) > 0:
            attachments = [await attachment.to_file() for attachment in msg.attachments if attachment.size <= 8000000]

            bad_attachments = [f'`<Bad File: {attachment.filename} | File Size: {attachment.size}>`' for attachment in msg.attachments if attachment.size > 8000000]
            if bad_attachments:
                if content:
                    content += '\n'
                content += '\n'.join(bad_attachments)
        else:
            attachments = ""

        if msg.embeds:
            e = msg.embeds[0]
            e_dict = e.to_dict()
        else:
            e = None
            e_dict = None

        msg2 = await self.send_sticky(channel, author, content, e, attachments)

        return msg2, content, e_dict

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

        data = self.db.find({'guild_id':message.guild.id, 'channel_id':channel.id})
        if not data:
            return

        async for sticky in data:
            if sticky['enabled'] is False:
                continue

            if sticky['counter'] >= (sticky['max_counter']-1):
                if (calendar.timegm(time.gmtime()) - sticky['msg_time']) > sticky['cooldown']:
                    try:
                        msg = await channel.fetch_message(sticky['msg_id'])
                        await msg.delete()

                    except discord.NotFound:
                        if e_dict:= sticky['msg']['embed_dict']:
                            e = discord.Embed.from_dict(e_dict)
                        else:
                            e = None

                        content = sticky['msg']['content']
                        
                        author = message.guild.get_member(sticky['author']) or await self.bot.fetch_user(sticky['author'])
                        msg = await self.send_sticky(channel, author, content, e, None)
                        await self.db.find_one_and_update(
                            {'guild_id':message.guild.id, 'channel_id':channel.id, 'msg_id':sticky['msg_id']},
                                {"$set":{
                                    'msg_id':msg.id,
                                    'counter':0,
                                    'msg_time': calendar.timegm(time.gmtime()),
                                }})
            else:
                await self.db.update_many({'guild_id':message.guild.id, 'channel_id':channel.id}, {"$set":{'counter':sticky['counter']+1}})

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.raw_models.RawMessageDeleteEvent):
        data = await self.db.find_one({'guild_id':payload.guild_id, 'channel_id':payload.channel_id, 'msg_id':payload.message_id})

        if not data:
            return

        channel = self.bot.get_channel(payload.channel_id)
        guild = self.bot.get_guild(payload.guild_id)
        author = guild.get_member(data['author']) or await self.bot.fetch_user(data['author'])

        try:
            msg_check = (payload.cached_message if payload.cached_message else await channel.fetch_message(payload.message_id))
        except discord.NotFound:
            if e_dict:= data['msg']['embed_dict']:
                e = discord.Embed.from_dict(e_dict)
            else:
                e = None

            content = data['msg']['content']
            msg_check = await self.send_sticky(channel, author, content, e, None)

            await self.db.find_one_and_update(
                {'guild_id':payload.guild_id, 'channel_id':payload.channel_id, 'msg_id':payload.message_id},
                    {"$set":{
                        'msg_id':msg_check.id,
                        'counter':0,
                        'msg_time': calendar.timegm(time.gmtime()),
                    }})
            return
        except discord.Forbidden:
            #await self.db.delete_one({'guild_id':payload.guild_id, 'channel_id':channel.id, 'msg_id':payload.message_id})
            return await self.bot.log_channel.send(f"Failed to fetch sticky message in {channel.mention} due to permissions issue.")

        msg, content, e_dict = await self.check_msg(channel, msg_check, author)

        await self.db.find_one_and_update(
            {'guild_id':payload.guild_id, 'channel_id':payload.channel_id, 'msg_id':payload.message_id},
                {"$set":{
                    'msg_id':msg.id,
                    'counter':0,
                    'msg_time': calendar.timegm(time.gmtime()),
                }})

    @commands.group(name="stick", usage="<counter> <cooldown (default is 30 seconds)>", invoke_without_command=True)
    @checks.has_permissions(PermissionLevel.MOD)
    async def stick_(self, ctx: commands.Context, max_counter: int, cooldown: Optional[int] = 30):
        """
        Stick a message to a channel

        **Usage:**
        Reply to a message: `{prefix}stick`
        `counter`: sticky message will be posted again after counter number of messages are sent to the channel
        `cooldown`: sticky message will be posted only if countdown is over
        """
        if ctx.author == self.bot.user:
            return
        if ctx.author.bot:
            return
        if not ctx.invoked_subcommand:
            try:
                if ctx.message.reference:
                    msg_check = await ctx.channel.fetch_message(ctx.message.reference.message_id)
                    if not (msg_check and isinstance(msg_check, discord.Message)):
                        return
                    msg, content, e_dict = await self.check_msg(ctx.channel, msg_check, ctx.message.reference.resolved.author)
                    await self.db.insert_one({
                        'guild_id':ctx.guild.id,
                        'msg_id':msg.id,
                        'msg':{
                            'embed_dict':e_dict,
                            'content':content,
                            },
                        'channel_id':ctx.channel.id,
                        'author':ctx.message.reference.resolved.author.id,
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
    async def stick_toggle(self, ctx: commands.Context, on_off: Optional[bool] = False, channel: discord.TextChannel = None):
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

async def setup(bot):
    await bot.add_cog(Sticky(bot))