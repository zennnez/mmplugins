# created for gothikit

import asyncio
import discord
from discord.ext import commands
from core import checks
from core.checks import PermissionLevel

class TStatusEmbed(commands.Cog):
    """Sets tickets' status"""
    def __init__(self, bot):
        self.bot = bot
        self.db = self.bot.plugin_db.get_partition(self)

        self.config = None
        self.guild = self.bot.modmail_guild

        self.channel = None
        self.msg = None
        self.embed = None

    async def cog_load(self):
        data = {
            "channel": None,
            "msg": None,
            }

        self.config = await self.db.find_one({"_id": "config"})
        if self.config is None:
            await self.db.find_one_and_update({"_id": "config"}, {"$set": data}, upsert=True)

            self.config = await self.db.find_one({"_id": "config"})

        for k, v in data.items(): #remove once all data keys are defined
            if k not in self.config:
                self.config[k] = v
            
        if self.config.get("channel", None):
            self.channel = self.guild.get_channel(int(self.config.get("channel", None))) or await self.guild.fetch_channel(int(self.config.get("channel", None)))
            self.msg = await self.channel.fetch_message(int(self.config.get("msg", None)))
            self.embed = self.msg.embeds[0]

    async def _update_config(self):
        await self.db.find_one_and_update({"_id": "config"},
            {"$set": {
                "channel": self.channel.id if self.channel else None,
                "msg": self.msg.id if self.msg else None,
                },
            }, upsert=True)

    async def set_status(self, channel, status):
        log = await self.bot.api.get_log(channel.id)

        if channel.guild != self.guild or not log:
            return

        if self.msg:
            if self.embed.description == "No records yet" and status != "Closed":
                self.embed.description = f"\n{channel.mention}: *{status}*"
            elif status == "Closed":
                tickets = self.embed.description.split("\n")
                new_desc = str()
                for k in tickets:
                    if channel.mention not in k:
                        new_desc += f"\n{k}"

                if not new_desc:
                    new_desc = "No records yet"

                self.embed.description = new_desc
            else:
                self.embed.description += f"\n{channel.mention}: **{status}***"
            await self.msg.edit(embed=self.embed)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return

        if message.type != discord.MessageType.default:
            return

        ctx = await self.bot.get_context(message)
        if ctx.valid and ctx.command.qualified_name != "claim":
            return

        thread = None
        channel = message.channel
        recipient = message.author

        if ctx.command and ctx.command.qualified_name == "claim":
            claim_cog = self.bot.get_cog('ClaimThread')
            if not await claim_cog.check_claimer(ctx, ctx.author.id):
                return

            status = "Claimed"
            thread = await self.bot.threads.find(recipient=recipient)
        elif isinstance(channel, discord.DMChannel):
            status = "Open"
            thread = await self.bot.threads.find(recipient=recipient)

        else:
            status = "Awaiting Staff's Reply"
            thread = await self.bot.threads.find(channel=channel)

        if not thread:
            return

        channel = thread.channel

        if self.msg:
            tickets = self.embed.description.split("\n")
            new_desc = str()
            for k in tickets:
                if channel.mention in k:
                    new_desc += f"\n{channel.mention}: **{status}**"
                else:
                    new_desc += k

            self.embed.description = new_desc
            await self.msg.edit(embed=self.embed)

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        msg = None
        for _ in range(30):
            await asyncio.sleep(0.5)
            thread = await self.bot.threads.find(channel=channel)
            if thread and thread.ready:
                msg = await thread.get_genesis_message()
                if msg:
                    break

        if msg:
            await self.set_status(channel, "**Unclaimed**")

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        await self.set_status(channel, "Closed")

    @checks.has_permissions(PermissionLevel.ADMIN)
    @commands.group(name='ticketstatus', aliases=['tstatus'], invoke_without_command=True)
    async def ticketstatus_(self, ctx):
        """Ticket status commands"""
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.ADMIN)
    @ticketstatus_.command(name='channel')
    async def ticketstatus_channel(self, ctx, channel: discord.TextChannel = None):
        """Set all tickets status embed channel"""

        if channel:
            embed = discord.Embed(title="Tickets Status", color=self.bot.main_color, description="No records yet")
            msg = await channel.send(embed=embed)
            await msg.pin()

            self.channel = channel
            self.msg = msg
            self.embed = msg.embeds[0]
            await self._update_config()

            await ctx.message.add_reaction(ctx.bot.tick)
        else:
            await self.msg.delete()
            self.channel = None
            self.msg = None
            self.embed = None
            await self._update_config()

            await ctx.reply("Disabled status embed message")

async def setup(bot):
    await bot.add_cog(TStatusEmbed(bot))