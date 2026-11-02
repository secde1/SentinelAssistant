from rapidocr_onnxruntime import RapidOCR
o=RapidOCR()
res,_=o(r"D:\it-agent\data\ish\ocr1\p0_0_Im1.jpg")
for r in (res or []): print(r[1])
