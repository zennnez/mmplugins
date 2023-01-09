# created for Uncle LYHME#0001 (discord)

import discord
from discord.ext import commands

from core import checks
from core.models import PermissionLevel

class Status(discord.ui.View):
    def __init__(self, context: commands.Context, message):
        super().__init__(timeout=None)
        self.context = context
        self.user = context.author
        self.message = message

    @discord.ui.button(label='Done', style=discord.ButtonStyle.green)
    async def done(self, b, i):
        embed = self.message.embeds[0]
        if embed.title:
            embed.title = embed.title + ' (Completed)'
        embed.add_field(name="Done by", value=f'{self.user.mention}', inline=True)
        embed.color = self.context.bot.main_color
        await self.message.edit(embed=embed, view=None)
        self.stop()

    @discord.ui.button(label='Cancel', style=discord.ButtonStyle.red)
    async def cancel(self, b, i):
        embed = self.message.embeds[0]
        if embed.title:
            embed.title = embed.title + ' (Cancelled)'
        embed.add_field(name="Cancelled by", value=f'{self.user.mention}', inline=True)
        embed.color = self.context.bot.error_color
        await self.message.edit(embed=embed, view=None)
        self.stop()

class Todo(commands.Cog):
    """
    Tasks/ToDo's
    """
    def __init__(self, bot):
        self.bot = bot

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

        msg = await channel.send(embed=embed)
        await msg.edit(view=Status(ctx, msg))
        posted = discord.ui.Button(
            label="here",
            url=msg.jump_url,
            )
        await ctx.send('>>> **Posted**', components=posted)

    @staticmethod
    async def generate_embed(description: str):
        embed = discord.Embed()
        embed.colour = discord.Colour.blurple()
        embed.description = description

        return embed

async def setup(bot):
    await bot.add_cog(Todo(bot))
