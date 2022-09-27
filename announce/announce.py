#credits: https://github.com/officialpiyush/modmail-plugins/blob/master/announcement/announcement.py
#planned changes will be done soon

import discord
import typing
import re
from discord.ext import commands
from enum import IntEnum

from core import checks
from core.models import PermissionLevel

class Announce(commands.Cog):
    """
    Simple Announcements
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.group(aliases=["a"], invoke_without_command=True)
    @commands.guild_only()
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def announcement(self, ctx: commands.Context):
        """
        Make Announcements Easily
        """
        await ctx.send_help(ctx.command)

    @announcement.command()
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def start(
        self,
        ctx: commands.Context,
        role: typing.Optional[typing.Union[discord.Role, str]] = None,
    ):
        """
        Start an interactive session to create announcement
        Add the role in the command if you want to enable mentions
        **Example:**
        __Announcement with role mention:__
        {prefix}announcement start everyone
        __Announcement without role mention__
        {prefix}announcement start
        """

        # TODO: Enable use of reactions
        def check(msg: discord.Message):
            return ctx.author == msg.author and ctx.channel == msg.channel

  #      def check_reaction(reaction: discord.Reaction, user: discord.Member):
  #          return ctx.author == user and (str(reaction.emoji == "✅") or str(reaction.emoji) == "❌")

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

        def footer_check(msg: discord.Message):
            return (
                ctx.author == msg.author
                and ctx.channel == msg.channel
                and (len(msg.content) < 2048)
            )

 #        def author_check(msg: discord.Message):
 #            return (
 #                    ctx.author == msg.author and ctx.channel == msg.channel and (len(msg.content) < 256)
 #            )

        def cancel_check(msg: discord.Message):
            if msg.content.lower() == "cancel" or msg.content.lower() == f"{ctx.prefix}cancel":
                return True
            else:
                return False

        if isinstance(role, discord.Role):
            role_mention = f"<@&{role.id}>"
            guild: discord.Guild = ctx.guild
            grole: discord.Role = guild.get_role(role.id)
            await grole.edit(mentionable=True)
        elif isinstance(role, str):
            if role == "here" or role == "@here":
                role_mention = "@here"
            elif role == "everyone" or role == "@everyone":
                role_mention = "@everyone"
        else:
            role_mention = ""

        await ctx.send("Starting an interactive process to create an announcement")

        await ctx.send(
            embed=await self.generate_embed("Do you want it to be an embed? `[y/n]`")
        )

        embed_res: discord.Message = await self.bot.wait_for("message", check=check)
        if cancel_check(embed_res) is True:
            await ctx.send("Cancelled!")
            return
        elif cancel_check(embed_res) is False and embed_res.content.lower() == "n":
            await ctx.send(
                embed=await self.generate_embed(
                    "Okay, let's do a no-embed announcement."
                    "\nWhat's the announcement?"
                )
            )
            announcement = await self.bot.wait_for("message", check=check)
            if cancel_check(announcement) is True:
                await ctx.send("Cancelled!")
                return
            else:
                await ctx.send(
                    embed=await self.generate_embed(
                        "To which channel should I send the announcement?"
                    )
                )
                channel: discord.Message = await self.bot.wait_for(
                    "message", check=check
                )
                if cancel_check(channel) is True:
                    await ctx.send("Cancelled!")
                    return
                else:
                    if channel.channel_mentions[0] is None:
                        await ctx.send("Cancelled as no channel was provided")
                        return
                    else:
                        await channel.channel_mentions[0].send(
                            f"{role_mention}\n{announcement.content}"
                        )
        elif cancel_check(embed_res) is False and embed_res.content.lower() == "y":
            embed = discord.Embed()
            await ctx.send(
                embed=await self.generate_embed(
                    "Should the embed have a title? `[y/n]`"
                )
            )
            t_res = await self.bot.wait_for("message", check=check)
            if cancel_check(t_res) is True:
                await ctx.send("Cancelled")
                return
            elif cancel_check(t_res) is False and t_res.content.lower() == "y":
                await ctx.send(
                    embed=await self.generate_embed(
                        "What should the title of the embed be?"
                        "\n**Must not exceed 256 characters**"
                    )
                )
                tit = await self.bot.wait_for("message", check=title_check)
                embed.title = tit.content

            await ctx.send(
                embed=await self.generate_embed(
                    "Should the announcement have a url? `[y/n]`"
                )
            )
            u_res = await self.bot.wait_for("message", check=check)
            if cancel_check(u_res) is True:
                await ctx.send("Cancelled")
                return
            elif cancel_check(u_res) is False and u_res.content.lower() == "y":
                await ctx.send(
                    embed=await self.generate_embed(
                        "Send a valid URL?"
                    )
                )
                eurl = await self.bot.wait_for("message", check=title_check)
                if t_res.content.lower() == "y":
                    embed.url = eurl.content

            await ctx.send(
                embed=await self.generate_embed(
                    "Should the embed have a description?`[y/n]`"
                )
            )
            d_res: discord.Message = await self.bot.wait_for("message", check=check)
            if cancel_check(d_res) is True:
                await ctx.send("Cancelled")
                return
            elif cancel_check(d_res) is False and d_res.content.lower() == "y":
                await ctx.send(
                    embed=await self.generate_embed(
                        "What do you want as the description for the embed?"
                        "\n**Must not exceed 2048 characters**"
                    )
                )
                des = await self.bot.wait_for("message", check=description_check)
                embed.description = des.content

            await ctx.send(
                embed=await self.generate_embed(
                    "Should the embed have a thumbnail?`[y/n]`"
                )
            )
            th_res: discord.Message = await self.bot.wait_for("message", check=check)
            if cancel_check(th_res) is True:
                await ctx.send("Cancelled")
                return
            elif cancel_check(th_res) is False and th_res.content.lower() == "y":
                await ctx.send(
                    embed=await self.generate_embed(
                        "What's the thumbnail of the embed? Enter a " "valid URL"
                    )
                )
                thu = await self.bot.wait_for("message", check=check)
                embed.set_thumbnail(url=thu.content)

            await ctx.send(
                embed=await self.generate_embed("Should the embed have a image?`[y/n]`")
            )
            i_res: discord.Message = await self.bot.wait_for("message", check=check)
            if cancel_check(i_res) is True:
                await ctx.send("Cancelled")
                return
            elif cancel_check(i_res) is False and i_res.content.lower() == "y":
                await ctx.send(
                    embed=await self.generate_embed(
                        "What's the image of the embed? Enter a " "valid URL"
                    )
                )
                i = await self.bot.wait_for("message", check=check)
                embed.set_image(url=i.content)

            await ctx.send(
                embed=await self.generate_embed("Will the embed have a footer?`[y/n]`")
            )
            f_res: discord.Message = await self.bot.wait_for("message", check=check)
            if cancel_check(f_res) is True:
                await ctx.send("Cancelled")
                return
            elif cancel_check(f_res) is False and f_res.content.lower() == "y":
                await ctx.send(
                    embed=await self.generate_embed(
                        "What do you want the footer of the embed to be?"
                        "\n**Must not exceed 2048 characters**"
                    )
                )
                foo = await self.bot.wait_for("message", check=footer_check)
                embed.set_footer(text=foo.content)

            await ctx.send(
                embed=await self.generate_embed(
                    "Do you want it to have a color?`[y/n]`"
                )
            )
            c_res: discord.Message = await self.bot.wait_for("message", check=check)
            if cancel_check(c_res) is True:
                await ctx.send("Cancelled!")
                return
            elif cancel_check(c_res) is False and c_res.content.lower() == "y":
                await ctx.send(
                    embed=await self.generate_embed(
                        "What color should the embed have? "
                        "Please provide a valid hex color\n"
                        "Or choose the deaults:\n"
                        "`imp`: important(ping a role)\n"
                        "`info`: info(important but no role ping)\n"
                        "`safe`: can be ignored (no role ping)\n"
                        "`role`: for reaction role message\n"
                        "`temp`: valid for short term (like bot maintenance)\n"
                        "`main`: bot main color"
                    )
                )
                colo = await self.bot.wait_for("message", check=check)
                if cancel_check(colo) is True:
                    await ctx.send("Cancelled!")
                    return
                elif colo.content.lower() == "imp":
                    embed.colour = 0xeb5342
                elif colo.content.lower() == "info":
                    embed.colour = 0x78dbed
                elif colo.content.lower() == "safe":
                    embed.colour = 0xa2d69a
                elif colo.content.lower() == "role":
                    embed.colour = 0xC8B1E2
                elif colo.content.lower() == "temp":
                    embed.colour = 0x2f3136
                elif colo.content.lower() == "main":
                    embed.colour = self.bot.main_color
                else:
                    match = re.search(
                        r"^#(?:[0-9a-fA-F]{3}){1,2}$", colo.content
                    )
                    if match:
                        embed.colour = int(
                            colo.content.replace("#", "0x"), 0
                        )
                    else:
                        await ctx.send(
                            "Failed! Not a valid hex color, get yours from "
                            "https://www.google.com/search?q=color+picker"
                        )
                        return

            await ctx.send(
                embed=await self.generate_embed(
                    "In which channel should I send the announcement?"
                )
            )
            channel: discord.Message = await self.bot.wait_for("message", check=check)
            if cancel_check(channel) is True:
                await ctx.send("Cancelled!")
                return
            else:
                if channel.channel_mentions[0] is None:
                    await ctx.send("Cancelled as no channel was provided")
                    return
                else:
                    schan = channel.channel_mentions[0]
            await ctx.send(
                "Here is how the embed looks like: Send it? `[y/n]`", embed=embed
            )
            s_res = await self.bot.wait_for("message", check=check)
            if cancel_check(s_res) is True or s_res.content.lower() == "n":
                await ctx.send("Cancelled")
                return
            else:
                await schan.send(f"{role_mention}", embed=embed)
        if isinstance(role, discord.Role):
            guild: discord.Guild = ctx.guild
            grole: discord.Role = guild.get_role(role.id)
            if grole.mentionable is True:
                await grole.edit(mentionable=False)

    @announcement.command(aliases=["native", "n", "q"])
    @checks.has_permissions(PermissionLevel.ADMIN)
    async def quick(
        self,
        ctx: commands.Context,
        channel: discord.TextChannel,
        role: typing.Optional[typing.Union[discord.Role, str]],
        *,
        msg: str,
    ):
        """
        An old way of making announcements
        **Usage:**
        {prefix}announcement quick #channel <OPTIONAL role> message
        """
        if isinstance(role, discord.Role):
            guild: discord.Guild = ctx.guild
            grole: discord.Role = guild.get_role(role.id)
            await grole.edit(mentionable=True)
            role_mention = f"<@&{role.id}>"
        elif isinstance(role, str):
            if role == "here" or role == "@here":
                role_mention = "@here"
            elif role == "everyone" or role == "@everyone":
                role_mention = "@everyone"
            else:
                msg = f"{role} {msg}"
                role_mention = ""

        await channel.send(f"{role_mention}\n{msg}")
        await ctx.send("Done")

        if isinstance(role, discord.Role):
            guild: discord.Guild = ctx.guild
            grole: discord.Role = guild.get_role(role.id)
            if grole.mentionable is True:
                await grole.edit(mentionable=False)

    @staticmethod
    async def generate_embed(description: str):
        embed = discord.Embed()
        embed.colour = discord.Colour.blurple()
        embed.description = description

        return embed


async def setup(bot):
    await bot.add_cog(Announce(bot))
