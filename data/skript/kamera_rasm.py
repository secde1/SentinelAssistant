import cv2,time,sys
cap=cv2.VideoCapture(0,cv2.CAP_DSHOW)
if not cap.isOpened(): print("OPEN_FAIL"); sys.exit(2)
for _ in range(25):
    cap.read(); time.sleep(0.1)
ok,f=cap.read(); cap.release()
if not ok: print("READ_FAIL"); sys.exit(3)
cv2.imwrite(r"D:\it-agent\data\ish\kamera\laptop.jpg",f); print("OK",f.shape)

