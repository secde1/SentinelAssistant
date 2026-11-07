import sys, ctypes, ctypes.wintypes as wt
from PIL import Image
import win32gui, win32ui, win32con

pid_title = sys.argv[1] if len(sys.argv) > 1 else "Google Chrome"
out = sys.argv[2] if len(sys.argv) > 2 else r"D:\it-agent\data\ish\chrome_tv.png"
found = []
def cb(h, _):
    if win32gui.IsWindowVisible(h) and pid_title in win32gui.GetWindowText(h):
        found.append(h)
win32gui.EnumWindows(cb, None)
if not found:
    print("window not found"); sys.exit(1)
h = found[0]
l, t, r, b = win32gui.GetWindowRect(h)
w, hh = r - l, b - t
hdc = win32gui.GetWindowDC(h)
mdc = win32ui.CreateDCFromHandle(hdc)
sdc = mdc.CreateCompatibleDC()
bmp = win32ui.CreateBitmap(); bmp.CreateCompatibleBitmap(mdc, w, hh)
sdc.SelectObject(bmp)
ctypes.windll.user32.PrintWindow(h, sdc.GetSafeHdc(), 2)
info = bmp.GetInfo(); bits = bmp.GetBitmapBits(True)
img = Image.frombuffer("RGB", (info["bmWidth"], info["bmHeight"]), bits, "raw", "BGRX", 0, 1)
img.save(out)
print("saved", out, img.size)
from rapidocr_onnxruntime import RapidOCR
res, _ = RapidOCR()(out)
open(r'D:\it-agent\data\ish\chrome_ocr.txt','w',encoding='utf-8').write('\n'.join(t for _,t,_ in (res or [])))

