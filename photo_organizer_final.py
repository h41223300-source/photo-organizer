import os, re, csv, shutil, hashlib, threading, queue, sys, json, subprocess
from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP="사진관리 FINAL"
IMAGE_EXT={'.jpg','.jpeg','.png','.gif','.tif','.tiff','.bmp','.webp','.heic','.heif','.avif','.dng','.raw','.cr2','.cr3','.nef','.arw','.orf','.rw2','.raf','.pef','.srw'}
VIDEO_EXT={'.mov','.mp4','.m4v','.avi','.mts','.m2ts','.3gp','.webm','.mkv'}
HIGH_TAGS=["DateTimeOriginal","DateTimeDigitized","CreateDate"]
VIDEO_TAGS=["creation_time","com.apple.quicktime.creationdate","date","encoded_date"]

def parse_dt(v):
    if not v: return None
    s=str(v).strip().replace("\x00","")
    # ISO / EXIF / ffprobe variants; timezone retained only for parsing, wall-clock capture time preserved.
    s=re.sub(r'^(\d{4}):(\d{2}):(\d{2})', r'\1-\2-\3', s)
    m=re.search(r'(?<!\d)(19\d{2}|20\d{2})[-:](0[1-9]|1[0-2])[-:]([0-2]\d|3[01])[ T](\d{2}):(\d{2}):(\d{2})(?:\.\d+)?',s)
    if m:
        try:
            d=datetime(*map(int,m.groups()))
            if 1900 <= d.year <= datetime.now().year+1: return d
        except: pass
    m=re.search(r'(?<!\d)(19\d{2}|20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])(?:[_ T-]?([0-2]\d)[-_.:]?([0-5]\d)[-_.:]?([0-5]\d))?',s)
    if m:
        try:
            g=m.groups()
            return datetime(int(g[0]),int(g[1]),int(g[2]),int(g[3] or 0),int(g[4] or 0),int(g[5] or 0))
        except: pass
    return None

def pillow_date(path):
    try:
        from PIL import Image, ExifTags
        with Image.open(path) as im:
            ex=im.getexif()
            cand=[]
            # top-level
            for k,v in ex.items():
                n=ExifTags.TAGS.get(k,str(k))
                if n in HIGH_TAGS: cand.append((n,v))
            # ExifIFD (critical for DateTimeOriginal)
            try:
                sub=ex.get_ifd(0x8769)
                for k,v in sub.items():
                    n=ExifTags.TAGS.get(k,str(k))
                    if n in HIGH_TAGS: cand.append((n,v))
            except: pass
            pr={"DateTimeOriginal":0,"DateTimeDigitized":1,"CreateDate":2}
            cand.sort(key=lambda x:pr.get(x[0],9))
            for n,v in cand:
                d=parse_dt(v)
                if d: return d,"EXIF:"+n,"높음"
    except: pass
    return None

def heif_date(path):
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
        r=pillow_date(path)
        if r:
            d,m,c=r
            return d,"HEIC-"+m,c
    except: pass
    return None

def ffprobe_exe():
    # imageio-ffmpeg supplies a bundled ffmpeg; ffprobe may also be on PATH.
    return shutil.which("ffprobe")

def video_date(path):
    probe=ffprobe_exe()
    if probe:
        try:
            cmd=[probe,"-v","quiet","-print_format","json","-show_format","-show_streams",str(path)]
            r=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",
                             timeout=30,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0))
            data=json.loads(r.stdout or "{}")
            pools=[]
            pools.append((data.get("format") or {}).get("tags") or {})
            for st in data.get("streams") or []: pools.append(st.get("tags") or {})
            # Explicit creation tags first.
            for key in VIDEO_TAGS:
                for tags in pools:
                    for k,v in tags.items():
                        if k.lower()==key.lower():
                            d=parse_dt(v)
                            if d: return d,"영상메타데이터:"+k,"중간"
        except: pass
    # mutagen MP4 atoms (works without ffprobe for many MP4/MOV)
    try:
        from mutagen.mp4 import MP4
        f=MP4(str(path))
        tags=f.tags or {}
        for k,v in tags.items():
            lk=str(k).lower()
            if "day" in lk or "date" in lk or "creation" in lk:
                vals=v if isinstance(v,list) else [v]
                for x in vals:
                    d=parse_dt(x)
                    if d: return d,"MP4태그:"+str(k),"중간"
    except: pass
    return None

# Only use filenames when they contain a recognizable camera/export date pattern.
FNP=[
 re.compile(r'(?i)(?:IMG|VID|PXL|Screenshot|Screenshot_|KakaoTalk_|SAVE_|received_)?[-_ ]?(20\d{2})(0[1-9]|1[0-2])([0-2]\d|3[01])[_ -]?([0-2]\d)?([0-5]\d)?([0-5]\d)?'),
 re.compile(r'(?<!\d)(20\d{2}|19\d{2})[-_.](0[1-9]|1[0-2])[-_.]([0-2]\d|3[01])(?:[_ T-]([0-2]\d)[-_.:]?([0-5]\d)[-_.:]?([0-5]\d))?')
]
def filename_date(path):
    s=path.stem
    for p in FNP:
        m=p.search(s)
        if m:
            try:
                g=m.groups()
                d=datetime(int(g[0]),int(g[1]),int(g[2]),int(g[3] or 0),int(g[4] or 0),int(g[5] or 0))
                return d,"파일명 날짜","중간"
            except: pass
    return None

def capture_date(path):
    ext=path.suffix.lower()
    if ext in {'.heic','.heif','.avif'}:
        r=heif_date(path)
        if r:return r
    if ext in IMAGE_EXT:
        r=pillow_date(path)
        if r:return r
    if ext in VIDEO_EXT:
        r=video_date(path)
        if r:return r
    r=filename_date(path)
    if r:return r
    return None,None,"확인필요"

def sha256(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()

def unique_dest(folder,name):
    p=folder/name
    if not p.exists(): return p
    stem,suf=Path(name).stem,Path(name).suffix
    i=2
    while True:
        q=folder/f"{stem}_{i}{suf}"
        if not q.exists(): return q
        i+=1

def same_path(a,b):
    try:return os.path.samefile(a,b)
    except:return os.path.abspath(a).lower()==os.path.abspath(b).lower()

class App:
    def __init__(self,root):
        self.root=root; root.title(APP); root.geometry("820x570")
        self.src=tk.StringVar(); self.dst=tk.StringVar()
        self.videos=tk.BooleanVar(value=True); self.dups=tk.BooleanVar(value=False)
        self.q=queue.Queue()
        f=ttk.Frame(root,padding=14); f.pack(fill="both",expand=True)
        ttk.Label(f,text="원본 폴더 (읽기만 함)").grid(row=0,column=0,sticky="w")
        ttk.Entry(f,textvariable=self.src,width=76).grid(row=1,column=0,sticky="ew",padx=(0,8))
        ttk.Button(f,text="찾아보기",command=lambda:self.pick(self.src)).grid(row=1,column=1)
        ttk.Label(f,text="정리본 저장 폴더").grid(row=2,column=0,sticky="w",pady=(12,0))
        ttk.Entry(f,textvariable=self.dst,width=76).grid(row=3,column=0,sticky="ew",padx=(0,8))
        ttk.Button(f,text="찾아보기",command=lambda:self.pick(self.dst)).grid(row=3,column=1)
        ttk.Checkbutton(f,text="동영상도 정리 (MOV/MP4 등)",variable=self.videos).grid(row=4,column=0,sticky="w",pady=(12,0))
        ttk.Checkbutton(f,text="완전 동일 중복파일도 중복검토 폴더에 복사",variable=self.dups).grid(row=5,column=0,sticky="w")
        ttk.Label(f,text="실제 촬영/생성 메타데이터 우선 → 신뢰 가능한 파일명 → 없으면 촬영일_확인필요 / 파일 수정일은 사용하지 않음").grid(row=6,column=0,columnspan=2,sticky="w",pady=(10,4))
        self.pb=ttk.Progressbar(f,mode="determinate"); self.pb.grid(row=7,column=0,columnspan=2,sticky="ew",pady=8)
        self.status=ttk.Label(f,text="준비됨"); self.status.grid(row=8,column=0,columnspan=2,sticky="w")
        self.log=tk.Text(f,height=16,state="disabled"); self.log.grid(row=9,column=0,columnspan=2,sticky="nsew",pady=8)
        bf=ttk.Frame(f); bf.grid(row=10,column=0,columnspan=2,sticky="e")
        self.startb=ttk.Button(bf,text="정리 시작",command=self.start); self.startb.pack(side="left",padx=4)
        ttk.Button(bf,text="종료",command=root.destroy).pack(side="left")
        f.columnconfigure(0,weight=1); f.rowconfigure(9,weight=1); root.after(100,self.poll)
    def pick(self,var):
        p=filedialog.askdirectory()
        if p:var.set(p)
    def write(self,s):
        self.log.configure(state="normal"); self.log.insert("end",s+"\n"); self.log.see("end"); self.log.configure(state="disabled")
    def start(self):
        s,d=Path(self.src.get()),Path(self.dst.get())
        if not s.is_dir():return messagebox.showerror(APP,"원본 폴더를 선택하세요.")
        if not self.dst.get():return messagebox.showerror(APP,"정리본 저장 폴더를 선택하세요.")
        d.mkdir(parents=True,exist_ok=True)
        try:
            if same_path(s,d) or str(d.resolve()).lower().startswith(str(s.resolve()).lower()+os.sep):
                return messagebox.showerror(APP,"정리본 폴더는 원본 폴더 내부가 아닌 별도 위치를 선택하세요.")
        except:pass
        self.startb.config(state="disabled"); self.pb["value"]=0; self.write("검사를 시작합니다...")
        threading.Thread(target=self.worker,args=(s,d),daemon=True).start()
    def worker(self,s,d):
        exts=set(IMAGE_EXT)|(VIDEO_EXT if self.videos.get() else set())
        files=[p for p in s.rglob("*") if p.is_file() and p.suffix.lower() in exts]
        total=len(files); seen={}; rows=[]; copied=dupc=errors=review=0
        self.q.put(("max",max(total,1))); self.q.put(("log",f"대상 파일: {total:,}개"))
        for i,p in enumerate(files,1):
            try:
                dt,method,confidence=capture_date(p)
                h=sha256(p); duplicate=h in seen
                if dt:
                    rel=Path(f"{dt.year:04d}")/f"{dt.month:02d}"
                    note=""
                    dtstr=dt.strftime("%Y-%m-%d %H:%M:%S")
                else:
                    rel=Path("촬영일_확인필요")
                    note="실제 촬영/생성 메타데이터와 신뢰할 수 있는 파일명 날짜를 찾지 못함"
                    dtstr="촬영일 없음"; method="촬영일 없음"; review+=1
                if duplicate and not self.dups.get():
                    rows.append([p.name,dtstr,method,confidence,str(p),"","중복-건너뜀",seen[h],note]); dupc+=1
                else:
                    base=d/("중복검토" if duplicate else "")/rel
                    base.mkdir(parents=True,exist_ok=True); out=unique_dest(base,p.name)
                    shutil.copy2(p,out)
                    if p.stat().st_size!=out.stat().st_size:raise IOError("복사 후 파일 크기 불일치")
                    rows.append([p.name,dtstr,method,confidence,str(p),str(out),"중복-복사" if duplicate else "정상","",note])
                    copied+=1
                    if duplicate:dupc+=1
                seen.setdefault(h,str(p))
            except Exception as e:
                errors+=1; rows.append([p.name,"","오류","",str(p),"","오류","",str(e)])
            if i%10==0 or i==total:self.q.put(("progress",i,f"{i:,}/{total:,} 처리 중 — {p.name}"))
        report=d/"사진정리_결과.csv"
        with open(report,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f); w.writerow(["파일명","촬영일","날짜판정방식","신뢰도","원본경로","정리경로","중복여부/결과","중복원본","비고"]); w.writerows(rows)
        self.q.put(("done",f"완료: 복사 {copied:,}개 / 확인필요 {review:,}개 / 중복 {dupc:,}개 / 오류 {errors:,}개\n결과표: {report}"))
    def poll(self):
        try:
            while True:
                x=self.q.get_nowait()
                if x[0]=="max":self.pb["maximum"]=x[1]
                elif x[0]=="progress":self.pb["value"]=x[1];self.status.config(text=x[2])
                elif x[0]=="log":self.write(x[1])
                elif x[0]=="done":self.write(x[1]);self.status.config(text="완료");self.startb.config(state="normal");messagebox.showinfo(APP,x[1])
        except queue.Empty:pass
        self.root.after(100,self.poll)

if __name__=="__main__":
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except: pass
    root=tk.Tk(); App(root); root.mainloop()
