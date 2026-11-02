import sys
from pypdf import PdfReader
r=PdfReader(r"D:\it-agent\data\ish\inbox\20261102-150823_20260608121858.pdf")
import os
os.makedirs(r"D:\it-agent\data\ish\ocr1",exist_ok=True)
n=0
for i,p in enumerate(r.pages):
    for im in p.images:
        fn=r"D:\it-agent\data\ish\ocr1\p%d_%d_%s"%(i,n,im.name); open(fn,"wb").write(im.data); n+=1; print(fn)
