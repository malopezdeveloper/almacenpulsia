import os
from pathlib import Path
from django.conf import settings
from django.utils import timezone
from .models import LabelPrintJob

def _printer_name():
 import win32print
 preferred=os.getenv("LABEL_PRINTER_NAME","Brother QL-700").strip()
 names=[item[2] for item in win32print.EnumPrinters(win32print.PRINTER_ENUM_LOCAL|win32print.PRINTER_ENUM_CONNECTIONS)]
 exact=next((name for name in names if name.casefold()==preferred.casefold()),None)
 fuzzy=next((name for name in names if "brother" in name.casefold() and "ql-700" in name.casefold()),None)
 if not exact and not fuzzy: raise RuntimeError(f"No se encontró la impresora {preferred}. Instale el controlador Brother y compruebe que esté encendida.")
 return exact or fuzzy

def _render_and_print(identifier,copies,printer_name):
 import win32con,win32ui
 from PIL import Image,ImageDraw,ImageFont,ImageWin
 dc=win32ui.CreateDC(); dc.CreatePrinterDC(printer_name)
 width=max(1,dc.GetDeviceCaps(win32con.HORZRES)); height=max(1,dc.GetDeviceCaps(win32con.VERTRES))
 image=Image.new("RGB",(width,height),"white"); draw=ImageDraw.Draw(image); margin=max(4,int(min(width,height)*.05)); font_path=Path(os.environ.get("WINDIR",r"C:\Windows"))/"Fonts"/"arialbd.ttf"
 low,high,best=8,max(12,height*2),None
 while low<=high:
  size=(low+high)//2; font=ImageFont.truetype(str(font_path),size); box=draw.textbbox((0,0),identifier,font=font,stroke_width=max(1,size//45)); tw,th=box[2]-box[0],box[3]-box[1]
  if tw<=width-2*margin and th<=height-2*margin: best=font; low=size+1
  else: high=size-1
 if best is None: best=ImageFont.truetype(str(font_path),8)
 box=draw.textbbox((0,0),identifier,font=best,stroke_width=max(1,best.size//45)); x=(width-(box[2]-box[0]))//2-box[0]; y=(height-(box[3]-box[1]))//2-box[1]
 draw.text((x,y),identifier,font=best,fill="black",stroke_width=max(1,best.size//45),stroke_fill="black")
 dc.StartDoc(f"PULSIA {identifier}")
 try:
  dib=ImageWin.Dib(image)
  for _ in range(copies): dc.StartPage(); dib.draw(dc.GetHandleOutput(),(0,0,width,height)); dc.EndPage()
 finally: dc.EndDoc(); dc.DeleteDC()

def print_identifier(identifier,user,copies=2):
 job=LabelPrintJob.objects.create(identifier=identifier,copies=copies,requested_by=user)
 try:
  if os.name!="nt": raise RuntimeError("La impresión automática solo está disponible en el servidor Windows.")
  printer=_printer_name(); _render_and_print(identifier,copies,printer); job.printer_name=printer; job.status="printed"
 except Exception as exc: job.status="failed"; job.error=str(exc)
 job.completed_at=timezone.now(); job.save(update_fields=["printer_name","status","error","completed_at"]); return job
