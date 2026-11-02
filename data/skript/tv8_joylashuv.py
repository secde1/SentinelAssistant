from PIL import Image, ImageDraw, ImageFont
im=Image.open(r"D:\it-agent\data\ish\inbox\20261029-203556_rasm.jpg").convert("RGBA")
ov=Image.new("RGBA",im.size,(0,0,0,0)); d=ImageDraw.Draw(ov)
f=ImageFont.truetype("arial.ttf",26)
w,h,g=112,63,8; x0,y0=30,190
n=1
for r in range(2):
    for c in range(4):
        x=x0+c*(w+g); y=y0+r*(h+g)
        d.rectangle([x,y,x+w,y+h],fill=(20,20,30,215),outline=(0,200,255,255),width=3)
        d.text((x+w/2-8,y+h/2-14),str(n),fill=(255,255,255,255),font=f); n+=1
d.text((30,150),"8 x 55\" TV (2x4)",fill=(255,255,0,255),font=f)
out=Image.alpha_composite(im,ov).convert("RGB")
out.save(r"D:\it-agent\data\ish\tv8_joylashuv.jpg",quality=90)
print("ok")
