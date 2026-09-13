# -*- coding: utf-8 -*-
import os, csv, hashlib, shutil, threading, queue, datetime, sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

PHOTO_EXTS = {".jpg",".jpeg",".heic",".heif",".png",".gif",".tif",".tiff",".bmp",".webp",".dng",".raw",".cr2",".cr3",".nef",".arw",".orf",".rw2",".raf",".pef",".srw",".avif"}
VIDEO_EXTS = {".mov",".mp4",".m4v",".avi",".mts",".m2ts",".3gp"}
ALL_EXTS = PHOTO_EXTS | VIDEO_EXTS

def sha256_file(path, chunk=1024*1024):
    h=hashlib.sha256()
    with open(path,"rb") as f:
        while True:
            b=f.read(chunk)
            if not b: break
            h.update(b)
    return h.hexdigest()

def exif_date(path):
    try:
        from PIL import Image
        with Image.open(path) as im:
            ex=im.getexif()
            for key in (36867,36868,306):
                v=ex.get(key)
                if v:
                    s=str(v).replace(":","-",2)
                    return datetime.datetime.fromisoformat(s).strftime("%Y-%m-%d %H:%M:%S"), "EXIF"
    except Exception:
        pass
    return None, None

def capture_date(path):
    d, src = exif_date(path)
    if d: return d, src
    return datetime.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"), "파일수정일"

def unique_path(dst):
    if not dst.exists(): return dst
    stem, suf = dst.stem, dst.suffix
    i=1
    while True:
        p=dst.with_name(f"{stem}_{i:03d}{suf}")
        if not p.exists(): return p
        i+=1

class App:
    def __init__(self, root):
        self.root=root
        root.title("사진관리 - iCloud 사진 자동정리")
        root.geometry("820x650")
        root.minsize(760,600)
        self.q=queue.Queue(); self.running=False

        frm=ttk.Frame(root,padding=18); frm.pack(fill="both",expand=True)
        ttk.Label(frm,text="iCloud 사진 자동정리 / 중복검사",font=("맑은 고딕",18,"bold")).pack(anchor="w",pady=(0,15))

        self.src=tk.StringVar()
        self.dst=tk.StringVar()
        self.include_video=tk.BooleanVar(value=True)
        self.copy_dups=tk.BooleanVar(value=False)
        self.verify=tk.BooleanVar(value=True)

        self.add_path(frm,"① 원본 사진 폴더",self.src,True)
        self.add_path(frm,"② 정리할 폴더",self.dst,False)

        opt=ttk.LabelFrame(frm,text="안전 옵션",padding=10); opt.pack(fill="x",pady=10)
        ttk.Checkbutton(opt,text="동영상(MOV/MP4 등)도 함께 정리",variable=self.include_video).pack(anchor="w")
        ttk.Checkbutton(opt,text="완전 동일 중복파일을 '중복검토' 폴더에도 복사",variable=self.copy_dups).pack(anchor="w")
        ttk.Checkbutton(opt,text="복사 후 파일 크기 확인",variable=self.verify).pack(anchor="w")
        ttk.Label(opt,text="※ 원본 파일은 삭제하거나 이동하지 않습니다.",foreground="#555").pack(anchor="w",pady=(6,0))

        self.progress=ttk.Progressbar(frm,mode="determinate"); self.progress.pack(fill="x",pady=(15,5))
        self.status=tk.StringVar(value="준비되었습니다.")
        ttk.Label(frm,textvariable=self.status).pack(anchor="w")

        self.log=tk.Text(frm,height=17,wrap="word")
        self.log.pack(fill="both",expand=True,pady=10)

        btn=ttk.Frame(frm); btn.pack(fill="x")
        self.start=ttk.Button(btn,text="▶ 사진 정리 시작",command=self.start_job)
        self.start.pack(side="left")
        ttk.Button(btn,text="폴더 열기",command=self.open_dst).pack(side="left",padx=8)
        ttk.Button(btn,text="종료",command=root.destroy).pack(side="right")

        root.after(100,self.poll)

    def add_path(self,parent,label,var,source):
        row=ttk.Frame(parent); row.pack(fill="x",pady=5)
        ttk.Label(row,text=label,width=20).pack(side="left")
        ttk.Entry(row,textvariable=var).pack(side="left",fill="x",expand=True)
        ttk.Button(row,text="찾아보기",command=lambda:self.choose(var)).pack(side="left",padx=(8,0))

    def choose(self,var):
        p=filedialog.askdirectory()
        if p: var.set(p)

    def open_dst(self):
        p=self.dst.get()
        if os.path.isdir(p): os.startfile(p)
        else: messagebox.showinfo("안내","정리할 폴더를 먼저 선택하세요.")

    def logmsg(self,s):
        self.q.put(("log",s))

    def start_job(self):
        if self.running: return
        src=Path(self.src.get()); dst=Path(self.dst.get())
        if not src.is_dir(): messagebox.showerror("오류","원본 사진 폴더를 선택하세요."); return
        if not self.dst.get(): messagebox.showerror("오류","정리할 폴더를 선택하세요."); return
        if src.resolve()==dst.resolve():
            messagebox.showerror("오류","원본 폴더와 정리 폴더는 다르게 지정해야 합니다."); return
        dst.mkdir(parents=True,exist_ok=True)
        self.running=True; self.start.config(state="disabled")
        self.progress["value"]=0; self.log.delete("1.0","end")
        threading.Thread(target=self.worker,args=(src,dst),daemon=True).start()

    def worker(self,src,dst):
        try:
            files=[]
            for p in src.rglob("*"):
                if p.is_file() and p.suffix.lower() in ALL_EXTS:
                    if (not self.include_video.get()) and p.suffix.lower() in VIDEO_EXTS: continue
                    files.append(p)
            total=len(files); self.q.put(("max",total))
            seen={}; rows=[]; copied=0; dups=0; errors=0
            for i,p in enumerate(files,1):
                try:
                    h=sha256_file(p)
                    date, source=capture_date(p)
                    y,m=date[:4],date[5:7]
                    if h in seen:
                        dups+=1
                        cls="완전동일 중복"
                        same=str(seen[h])
                        if self.copy_dups.get():
                            dp=unique_path(dst/"중복검토"/y/m/p.name)
                            dp.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dp)
                    else:
                        seen[h]=p
                        dp=unique_path(dst/y/m/p.name)
                        dp.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dp)
                        if self.verify.get() and dp.stat().st_size != p.stat().st_size:
                            raise IOError("복사 후 파일 크기가 원본과 다릅니다.")
                        copied+=1; cls="정리완료"; same=""
                    rows.append([str(p),str(dp) if 'dp' in locals() else "",date,source,h,cls,same])
                    if i==1 or i%50==0 or i==total: self.q.put(("prog",i,total,copied,dups))
                except Exception as e:
                    errors+=1; rows.append([str(p),"", "", "", "", "오류",str(e)])
                    self.q.put(("log",f"[오류] {p.name}: {e}"))
            report=dst/"사진정리_결과.csv"
            with open(report,"w",newline="",encoding="utf-8-sig") as f:
                w=csv.writer(f); w.writerow(["원본경로","결과경로","촬영일","날짜기준","SHA-256","분류","비고"]); w.writerows(rows)
            self.q.put(("done",total,copied,dups,errors,str(report)))
        except Exception as e:
            self.q.put(("fatal",str(e)))

    def poll(self):
        try:
            while True:
                x=self.q.get_nowait()
                if x[0]=="log": self.log.insert("end",x[1]+"\n"); self.log.see("end")
                elif x[0]=="max": self.progress["maximum"]=x[1]
                elif x[0]=="prog":
                    _,i,total,c,d=x; self.progress["value"]=i
                    self.status.set(f"{i:,} / {total:,} 처리 | 정리 {c:,} | 동일중복 {d:,}")
                elif x[0]=="done":
                    _,t,c,d,e,r=x
                    self.running=False; self.start.config(state="normal")
                    self.status.set(f"완료: 전체 {t:,} | 정리 {c:,} | 동일중복 {d:,} | 오류 {e:,}")
                    messagebox.showinfo("사진 정리 완료",f"정리가 완료되었습니다.\n\n전체: {t:,}개\n정리: {c:,}개\n완전 동일 중복: {d:,}개\n오류: {e:,}개\n\n결과 CSV:\n{r}")
                elif x[0]=="fatal":
                    self.running=False; self.start.config(state="normal"); messagebox.showerror("오류",x[1])
        except queue.Empty: pass
        self.root.after(100,self.poll)

if __name__=="__main__":
    root=tk.Tk(); App(root); root.mainloop()
