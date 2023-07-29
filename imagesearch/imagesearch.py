import re
import discord
from discord.ext import commands
from core import checks
from core.models import PermissionLevel
from urllib import parse

class ImageSearch(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def replyLinks(self, ctx, url: str = None, saucenao=False, google=False, tineye=False, iqdb=False, yandex=False):
        urls = []
        if url:
            urls = [url]
            result = 'link'

        elif ctx.message.reference:
            reference = await ctx.channel.fetch_message(ctx.message.reference.message_id)
            if reference and isinstance(reference, discord.Message):
                if len(reference.attachments) > 0:
                    urls = self.getMessageAttachmentURLs(reference)
                    result = 'file'

        elif len(ctx.message.attachments) > 0:
            urls = self.getMessageAttachmentURLs(ctx.message)
            result = 'file'

        else:
            await ctx.send(":grey_question: You have not provided anything to perform reverse search on.")
            return

        index = 1
        for u in urls:
            embed = discord.Embed(color=self.bot.main_color)
            author_avatar = self.bot.user.default_avatar.url if self.bot.user.avatar.url == None else self.bot.user.avatar.url
            embed.set_thumbnail(url=author_avatar)

            if result == "file":
                embed.title = ":mag_right: Reverse searching attached files"
                embed.add_field(name="Attachment {} of {}:".format(index, len(urls)), value=u, inline=False)

            elif result == "link":
                embed.title = ":mag_right: Reverse searching provided link"
                embed.add_field(name="Provided link:", value=u, inline=False)

            if saucenao == True:
                embed.add_field(name="\u200b", value="**[SauceNAO]({})\n**".format(self.sauceLink(u)), inline=False)
            if google == True:
                embed.add_field(name="\u200b", value="**[Google]({})\n**".format(self.googleLink(u)), inline=False)
            if tineye == True:
                embed.add_field(name="\u200b", value="**[TinEye]({})\n**".format(self.tineyeLink(u)), inline=False)
            if iqdb == True:
                embed.add_field(name="\u200b", value="**[IQDB]({})\n**".format(self.iqdbLink(u)), inline=False)
            if yandex == True:
                embed.add_field(name="\u200b", value="**[Yandex]({})**".format(self.yandexLink(u)), inline=False)

            await ctx.send(embed=embed)
            del embed
            index += 1
        return

    def sauceLink(self, url: str):
        return "https://saucenao.com/search.php?url={}".format(parse.quote_plus(url))

    def googleLink(self, url: str):
        return "https://www.google.com/searchbyimage?&image_url={}".format(parse.quote_plus(url))

    def tineyeLink(self, url: str):
        return "https://www.tineye.com/search?url={}".format(parse.quote_plus(url))

    def iqdbLink(self, url: str):
        return "https://iqdb.org/?url={}".format(parse.quote_plus(url))

    def yandexLink(self, url: str):
        return "https://yandex.com/images/search?url={}&rpt=imageview".format(parse.quote_plus(url))

    def getMessageAttachmentURLs(self, message: discord.Message):
        urls = []
        for a in message.attachments:
            urls.append(a.url)
        return urls

    @checks.has_permissions(PermissionLevel.REGULAR)
    @commands.group(name="ris", invoke_without_command=True)
    async def ris(self, ctx):
        """
        Reverse Image Search
        Usage: `{prefix}ris`
        """
        if not ctx.invoked_subcommand:
            await ctx.send_help(ctx.command)

    @checks.has_permissions(PermissionLevel.REGULAR)
    @ris.command(name="all")
    async def risAll(self, ctx, *, url = None):
        """
        Reverse Image Search on all available platforms
        Either provide a url or an image attachment or reply to a message containing image attachment
        Usage: `{prefix}ris all <url>`
        """
        await self.replyLinks(ctx, url, saucenao=True, google=True, tineye=True, iqdb=True, yandex=True)

    @checks.has_permissions(PermissionLevel.REGULAR)
    @ris.command(name="saucenao", aliases=["s"])
    async def risSauce(self, ctx, *, url = None):
        """
        Reverse Image Search on saucenao
        Either provide a url or an image attachment or reply to a message containing image attachment
        Usage: `{prefix}ris s <url>`
        """
        await self.replyLinks(ctx, url, risnao=True)

    @checks.has_permissions(PermissionLevel.REGULAR)
    @ris.command(name="google", aliases=["g"])
    async def risGoogle(self, ctx, *, url = None):
        """
        Reverse Image Search on google
        Either provide a url or an image attachment or reply to a message containing image attachment
        Usage: `{prefix}ris g <url>`
        """
        await self.replyLinks(ctx, url, google=True)

    @checks.has_permissions(PermissionLevel.REGULAR)
    @ris.command(name="tineye", aliases=["t"])
    async def risTineye(self, ctx, *, url = None):
        """
        Reverse Image Search on tineye
        Either provide a url or an image attachment or reply to a message containing image attachment
        Usage: `{prefix}ris t <url>`
        """
        await self.replyLinks(ctx, url, tineye=True)

    @checks.has_permissions(PermissionLevel.REGULAR)
    @ris.command(name="iqdb", aliases=["i"])
    async def risIQDB(self, ctx, *, url = None):
        """
        Reverse Image Search on iqdb
        Either provide a url or an image attachment or reply to a message containing image attachment
        Usage: `{prefix}ris i <url>`
        """
        await self.replyLinks(ctx, url, iqdb=True)

    @checks.has_permissions(PermissionLevel.REGULAR)
    @ris.command(name="yandex", aliases=["y"])
    async def risYandex(self, ctx, *, url = None):
        """
        Reverse Image Search on yandex
        Either provide a url or an image attachment or reply to a message containing image attachment
        Usage: `{prefix}ris y <url>`
        """
        await self.replyLinks(ctx, url, yandex=True)

async def setup(bot):
    await bot.add_cog(ImageSearch(bot))
