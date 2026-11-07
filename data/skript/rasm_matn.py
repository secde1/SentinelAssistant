from PIL import Image, ImageDraw, ImageFont, ImageFilter
im=Image.open(r"D:\it-agent\data\ish\inbox\20261103-233353_rasm.jpg").convert("RGB")
W,H=im.size
lines=["у каждого свои грехи:","может быть, твои это не алкоголь,","воровство, прелюбодеяние,","а просто мысль о том, что ты лучше других"]
f=ImageFont.truetype(r"C:\Windows\Fonts\segoeuil.ttf",58)
lh=84
y0=int(H*0.84)-len(lines)*lh//2
lay=Image.new("RGBA",im.size,(0,0,0,0))
d=ImageDraw.Draw(lay)
col=(214,168,92,235)
for i,t in enumerate(lines):
    w=d.textlength(t,font=f)
    d.text(((W-w)/2,y0+i*lh),t,font=f,fill=col)
sh=Image.new("RGBA",im.size,(0,0,0,0))
sd=ImageDraw.Draw(sh)
for i,t in enumerate(lines):
    w=sd.textlength(t,font=f)
    sd.text(((W-w)/2+2,y0+i*lh+3),t,font=f,fill=(0,0,0,200))
sh=sh.filter(ImageFilter.GaussianBlur(4))
out=Image.alpha_composite(Image.alpha_composite(im.convert("RGBA"),sh),lay).convert("RGB")
out.save(r"D:\it-agent\data\ish\bmw_text2.jpg",quality=95)
out.resize((750,1000)).save(r"D:\it-agent\data\ish\bmw_prev2.jpg")
print(W,H)

