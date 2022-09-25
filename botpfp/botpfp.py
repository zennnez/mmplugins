import discord
from discord.ext import commands
from core.models import PermissionLevel
from core import checks

class BotPfP(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.pic = None

    @commands.command()
    @checks.has_permissions(PermissionLevel.MOD)
    async def botpfp(self, ctx):
        """
        Set bot pic
        """

        def check(msg: discord.Message):
            return ctx.author == msg.author and ctx.channel == msg.channel
        
        def cancel_check(msg: discord.Message):
            if msg.content == "cancel" or msg.content == f"{ctx.prefix}cancel":
                return True
            else:
                return False

        await ctx.send(embed=await self.generate_embed(
            f"**Bot Profile Picture**\n"
            f"Send an image or link to set as profile picture.\n\n"
            f"_send `cancel` if you want to cancel_"))
        pic: discord.Message = await self.bot.wait_for("message", check=check)
        if cancel_check(pic) is True:
            await ctx.send("Cancelled!")
            return
        else:
            if len(pic.attachments) > 0:
                attachment = pic.attachments[0]
                if attachment.filename.endswith(".jpg") or attachment.filename.endswith(".jpeg") or attachment.filename.endswith(".png") or attachment.filename.endswith(".webp"):
                    self.pic = attachment.url
            elif 'http' in pic.content:
                if pic.content.endswith("jpg") or pic.content.endswith("jpeg") or pic.content.endswith("png") or pic.content.endswith("webp") or pic.content.endswith("gif"):
                    self.pic = pic.content
            else:
                return await ctx.send(embed=await self.generate_embed("No image found!"))

            if self.pic is not None:
                try:
                    async with self.bot.session.get(self.pic) as picf:
                        if picf.status == 200:
                            await self.bot.user.edit(avatar=await picf.read())
                            await ctx.message.add_reaction('👍')
                except discord.HTTPException:
                    await ctx.send("Discord won't let me change pic, try again later")
                    await ctx.message.add_reaction('👎')

    @staticmethod
    async def generate_embed(description: str):
        embed = discord.Embed()
        embed.colour = discord.Colour.blurple()
        embed.description = description

        return embed

async def setup(bot):
    await bot.add_cog(BotPfP(bot))
