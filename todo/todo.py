# created for Uncle LYHME#0001 (discord)

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel

class Status(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label='Done', style=discord.ButtonStyle.green)
    async def done(self, i, b):
        embed = i.message.embeds[0]
        if embed.title:
            embed.title = embed.title + ' (Completed)'
        embed.add_field(name="Done by", value=f'{i.user.mention}', inline=True)
        embed.color = 0x69ff7a
        await i.response.edit_message(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.red)
    async def cancel(self, i, b):
        embed = i.message.embeds[0]
        if embed.title:
            embed.title = embed.title + ' (Cancelled)'
        embed.add_field(name="Cancelled by", value=f'{i.user.mention}', inline=True)
        embed.color = 0xff6969
        await i.response.edit_message(embed=embed, view=None)
        self.stop()

class Todo(commands.Cog):
    """
    Tasks/ToDo's
    """
    default_global = {
        "enabled": True,
        "channel": None,
    }
    def __init__(self, bot):
        self.bot = bot
        self.db = bot.api.get_plugin_partition(self)
        self.task = self.bot.loop.create_task(self.cog_load())
        self.global_config = None
        self.ch = None

    async def cog_load(self):
        self.global_config = await self.db.find_one({"_id": "todo"})
        if self.global_config is None:
            self.global_config = self.default_global
            await self.config_update()
            self.global_config = await self.db.find_one({"_id": "todo"})

        if self.global_config['channel']:
            try:
                self.ch = await self.bot.fetch_channel(self.global_config['channel'])
            except discord.NotFound:
                pass
            except discord.HTTPException:
                pass

    async def config_update(self):
        await self.db.find_one_and_update(
            {"_id": "todo"},
            {"$set": self.global_config},
            upsert=True,
        )

    def cog_unload(self):
        self.task.cancel()

    @commands.group(aliases=["task"], invoke_without_command=True)
    @commands.guild_only()
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def todo(self, ctx: commands.Context):
        """
        Base command group for tasks
        """
        await ctx.send_help(ctx.command)

    @todo.command()
    @checks.has_permissions(PermissionLevel.SUPPORTER)
    async def create(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        Create a ToDo task embed
        """

        def check(msg: discord.Message):
            return ctx.author == msg.author and ctx.channel == msg.channel

        def title_check(msg: discord.Message):
            return (
                ctx.author == msg.author
                and ctx.channel == msg.channel
                and (len(msg.content) < 256)
            )

        def description_check(msg: discord.Message):
            return (
                ctx.author == msg.author
                and ctx.channel == msg.channel
                and (len(msg.content) < 2048)
            )

        def cancel_check(msg: discord.Message):
            if msg.content.lower() == "cancel" or msg.content.lower() == f"{ctx.prefix}cancel":
                return True
            else:
                return False

        embed = discord.Embed(colour = 0x2f3136)
        embed.add_field(name="Created by", value=f'{ctx.author.mention}', inline=True)
        await ctx.send(
            embed=await self.generate_embed(
                "Send Title of the ToDo message\nSend `skip` to skip, `cancel` to cancel"
            )
        )
        tit = await self.bot.wait_for("message", check=title_check)
        if cancel_check(tit):
            await ctx.send("Cancelled")
            return
        elif tit.content.lower() == "skip":
            await ctx.send("Skipped")
        else:
            embed.title = tit.content

        await ctx.send(
            embed=await self.generate_embed(
                "Send Description of the ToDo message\nSend `skip` to skip, `cancel` to cancel"
            )
        )
        des = await self.bot.wait_for("message", check=description_check)
        if cancel_check(des) is True:
            await ctx.send("Cancelled")
            return
        elif des.content.lower() == "skip":
            await ctx.send("Skipped")
        else:
            embed.description = des.content

        msg = await channel.send(embed=embed, view=Status())
        posted = discord.ui.Button(
            label="here",
            url=msg.jump_url,
            )
        await ctx.send('>>> **Posted**', components=posted)

    @todo.command()
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def channel(self, ctx: commands.Context, channel: discord.TextChannel):
        """
        ToDo channel
        """
        self.global_config['channel'] = channel.id
        self.ch = channel
        await self.config_update()
        await ctx.message.add_reaction('✅')

    @checks.has_permissions(PermissionLevel.MOD)
    @todo.command()
    async def toggle(self, ctx):
        """Toggle ToDo no/off"""
        self.global_config['enabled'] = not self.global_config['enabled']
        await self.config_update()
        await ctx.send(
            embed=await self.generate_embed(
                f"**Status:** {'Enabled' if self.global_config['enabled'] else 'Disabled'}"
            )
        )

    @staticmethod
    async def generate_embed(description: str):
        embed = discord.Embed()
        embed.colour = discord.Colour.blurple()
        embed.description = description

        return embed

    @commands.Cog.listener()
    async def on_message(self, message):
        author = message.author
        if author.bot:
            return

        if message.type != discord.MessageType.default:
            return

        if not message.guild or not message.content:
            return

        if not self.global_config['enabled']:
            return

        if message.channel == self.ch:
            embed = discord.Embed(colour = 0x2f3136)
            embed.add_field(name="Created by", value=f'{author.mention}', inline=True)
            embed.description = message.content
            await message.channel.send(embed=embed, view=Status())
            await message.delete()

async def setup(bot):
    await bot.add_cog(Todo(bot))
