import os, re, csv, shutil, hashlib, subprocess, threading, queue, sys, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP = "사진관리 ULTIMATE"
IMAGE_EXT = {'.jpg','.jpeg','.png','.gif','.tif','.tiff','.bmp','.webp','.heic','.heif','.avif','.dng','.raw','.cr2','.cr3','.nef','.arw','.orf','.rw2','.raf','.pef','.srw'}
VIDEO_EXT = {'.mov','.mp4','.m4v','.avi','.mts','.m2ts','.3gp','.mkv','.wmv'}
DATE_MIN = datetime(1990,1,1)
DATE_MAX = datetime.now() + timedelta(days=2)

def resource_path(name):
    return os.path.join(getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(__file__))), name)

def ffprobe_path():
    p = resource_path("ffprobe.exe")
    return p if os.path.exists(p) else shutil.which("ffprobe")

def valid(d):
    return isinstance(d, datetime) and DATE_MIN <= d.replace(tzinfo=None) <= DATE_MAX

def normalize_dt(s, utc_to_local=False):
    if s is None: return None
    s = str(s).strip()
    if not s: return None
    # EXIF: YYYY:MM:DD HH:MM:SS; ISO; QuickTime
    s2 = re.sub(r'^(\d{4}):(\d{2}):(\d{2})', r'\1-\2-\3', s)
    try:
        z = s2.replace('Z', '+00:00')
        d = datetime.fromisoformat(z)
        if d.tzinfo:
            if utc_to_local:
                d = d.astimezone().replace(tzinfo=None)
            else:
                d = d.replace(tzinfo=None)
        return d if valid(d) else None
    except: pass
    for fmt in ("%Y-%m-%d %H:%M:%S","%Y-%m-%d %H:%M:%S.%f","%Y-%m-%d","%Y%m%d_%H%M%S","%Y%m%d%H%M%S"):
        try:
            d=datetime.strptime(s2[:26],fmt)
            if valid(d): return d
        except: pass
    m=re.search(r'(19\d{2}|20\d{2})[-:/]?(\d{2})[-:/]?(\d{2})[ T_-]?(\d{2})?:?(\d{2})?:?(\d{2})?',s2)
    if m:
        try:
            d=datetime(int(m[1]),int(m[2]),int(m[3]),int(m[4] or 0),int(m[5] or 0),int(m[6] or 0))
            return d if valid(d) else None
        except: pass
    return None

def pillow_exif(path):
    try:
        from PIL import Image, ExifTags
        with Image.open(path) as im:
            ex=im.getexif()
            vals=[]
            # ExifIFD first
            try:
                sub=ex.get_ifd(0x8769)
                for k,v in sub.items():
                    n=ExifTags.TAGS.get(k,str(k))
                    if n in ("DateTimeOriginal","DateTimeDigitized"):
                        vals.append((0 if n=="DateTimeOriginal" else 1,n,v))
            except: pass
            for k,v in ex.items():
                n=ExifTags.TAGS.get(k,str(k))
                if n in ("DateTimeOriginal","DateTimeDigitized","DateTime"):
                    vals.append(({"DateTimeOriginal":0,"DateTimeDigitized":1,"DateTime":2}[n],n,v))
            for _,n,v in sorted(vals):
                d=normalize_dt(v)
                if d: return d, "EXIF:"+n, "높음"
    except: pass
    return None

def heif_exif(path):
    try:
        from PIL import Image, ExifTags
        import pillow_heif
        pillow_heif.register_heif_opener()
        return pillow_exif(path)
    except:
        return None

def ffprobe_date(path):
    tool=ffprobe_path()
    if not tool: return None
    try:
        cmd=[tool,"-v","quiet","-print_format","json","-show_format","-show_streams",str(path)]
        cp=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8",errors="replace",
                          timeout=30,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0))
        data=json.loads(cp.stdout or "{}")
        candidates=[]
        # Prefer QuickTime/format creation_time, then stream creation_time/encoded_date
        fmt=data.get("format",{}) or {}
        tags=fmt.get("tags",{}) or {}
        for key in ("com.apple.quicktime.creationdate","creation_time","date","encoded_date"):
            for k,v in tags.items():
                if k.lower()==key.lower(): candidates.append((key,v))
        for st in data.get("streams",[]) or []:
            tags=st.get("tags",{}) or {}
            for key in ("com.apple.quicktime.creationdate","creation_time","date","encoded_date"):
                for k,v in tags.items():
                    if k.lower()==key.lower(): candidates.append((key,v))
        for key,val in candidates:
            d=normalize_dt(val, utc_to_local=True)
            if d: return d, "영상메타데이터:"+key, "높음" if "creation" in key.lower() else "중간"
    except: pass
    return None

def filename_date(path):
    s=path.stem
    patterns=[
        r'(?<!\d)(19\d{2}|20\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])[-_ T]?(?:([0-2]\d)[-_.:]?([0-5]\d)[-_.:]?([0-5]\d))?',
        r'(?:IMG|VID|PXL)[-_]?(20\d{6})[_-]?(\d{6})'
    ]
    m=re.search(patterns[0],s,re.I)
    if m:
        try:
            d=datetime(int(m[1]),int(m[2]),int(m[3]),int(m[4] or 0),int(m[5] or 0),int(m[6] or 0))
            if valid(d): return d,"파일명 날짜","중간"
        except: pass
    m=re.search(patterns[1],s,re.I)
    if m:
        try:
            d=datetime.strptime(m[1]+m[2],"%Y%m%d%H%M%S")
            if valid(d): return d,"파일명 날짜","중간"
        except: pass
    # Unix timestamp only when filename convention strongly indicates it (e.g. SODA_1610689473)
    m=re.search(r'(?i)(?:SODA|VID|video)[_-](1[0-9]{9})(?!\d)',s)
    if m:
        try:
            d=datetime.fromtimestamp(int(m[1]))
            if valid(d): return d,"파일명 Unix timestamp","중간"
        except: pass
    return None

def get_capture_date(path):
    ext=path.suffix.lower()
    if ext in IMAGE_EXT:
        r=heif_exif(path) if ext in ('.heic','.heif') else pillow_exif(path)
        if r: return r
    if ext in VIDEO_EXT:
        r=ffprobe_date(path)
        if r: return r
    r=filename_date(path)
    if r: return r
    return None, "촬영일 없음", "확인필요"

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

def same_or_child(a,b):
    try:
        ar=str(Path(a).resolve()).lower().rstrip("\\/")
        br=str(Path(b).resolve()).lower().rstrip("\\/")
        return ar==br or br.startswith(ar+os.sep)
    except: return False

class App:
    def __init__(self,root):
        self.root=root; root.title(APP); root.geometry("820x570")
        self.src=tk.StringVar(); self.dst=tk.StringVar(); self.videos=tk.BooleanVar(value=True); self.dups=tk.BooleanVar(value=False)
        self.q=queue.Queue()
        f=ttk.Frame(root,padding=14); f.pack(fill="both",expand=True)
        ttk.Label(f,text="원본 폴더 (읽기 전용 / 원본 삭제·이동 없음)").grid(row=0,column=0,sticky="w")
        ttk.Entry(f,textvariable=self.src,width=76).grid(row=1,column=0,sticky="ew",padx=(0,8))
        ttk.Button(f,text="찾아보기",command=lambda:self.pick(self.src)).grid(row=1,column=1)
        ttk.Label(f,text="정리본 저장 폴더").grid(row=2,column=0,sticky="w",pady=(12,0))
        ttk.Entry(f,textvariable=self.dst,width=76).grid(row=3,column=0,sticky="ew",padx=(0,8))
        ttk.Button(f,text="찾아보기",command=lambda:self.pick(self.dst)).grid(row=3,column=1)
        ttk.Checkbutton(f,text="동영상 포함 (MOV/MP4/M4V 등)",variable=self.videos).grid(row=4,column=0,sticky="w",pady=(12,0))
        ttk.Checkbutton(f,text="완전 동일 중복도 '중복검토'에 복사",variable=self.dups).grid(row=5,column=0,sticky="w")
        ttk.Label(f,text="판정 순서: 사진 EXIF/HEIC → 영상 내부 생성일 → 신뢰 가능한 파일명 날짜 → 없으면 '촬영일_확인필요'").grid(row=6,column=0,columnspan=2,sticky="w",pady=(10,2))
        ttk.Label(f,text="※ Windows 파일 수정일은 촬영일로 사용하지 않습니다.").grid(row=7,column=0,columnspan=2,sticky="w")
        self.pb=ttk.Progressbar(f,mode="determinate"); self.pb.grid(row=8,column=0,columnspan=2,sticky="ew",pady=8)
        self.status=ttk.Label(f,text="준비됨"); self.status.grid(row=9,column=0,columnspan=2,sticky="w")
        self.log=tk.Text(f,height=15,state="disabled"); self.log.grid(row=10,column=0,columnspan=2,sticky="nsew",pady=8)
        bf=ttk.Frame(f); bf.grid(row=11,column=0,columnspan=2,sticky="e")
        self.startb=ttk.Button(bf,text="정리 시작",command=self.start); self.startb.pack(side="left",padx=4)
        ttk.Button(bf,text="종료",command=root.destroy).pack(side="left")
        f.columnconfigure(0,weight=1); f.rowconfigure(10,weight=1)
        root.after(100,self.poll)

    def pick(self,var):
        p=filedialog.askdirectory()
        if p: var.set(p)

    def write(self,s):
        self.log.configure(state="normal"); self.log.insert("end",s+"\n"); self.log.see("end"); self.log.configure(state="disabled")

    def start(self):
        s=Path(self.src.get()); d=Path(self.dst.get())
        if not s.is_dir(): return messagebox.showerror(APP,"원본 폴더를 선택하세요.")
        if not str(d): return messagebox.showerror(APP,"정리본 저장 폴더를 선택하세요.")
        d.mkdir(parents=True,exist_ok=True)
        if same_or_child(s,d): return messagebox.showerror(APP,"정리본 저장 폴더는 원본 폴더 밖의 별도 위치를 선택하세요.")
        self.startb.config(state="disabled"); self.pb["value"]=0; self.write("검사를 시작합니다...")
        threading.Thread(target=self.worker,args=(s,d),daemon=True).start()

    def worker(self,s,d):
        exts=set(IMAGE_EXT)|(VIDEO_EXT if self.videos.get() else set())
        files=[p for p in s.rglob("*") if p.is_file() and p.suffix.lower() in exts]
        total=len(files); seen={}; rows=[]; copied=dupc=errors=review=0
        self.q.put(("max",max(total,1))); self.q.put(("log",f"대상 파일: {total:,}개"))
        for i,p in enumerate(files,1):
            try:
                dt,method,confidence=get_capture_date(p)
                h=sha256(p); duplicate=h in seen
                if dt:
                    date_text=dt.strftime("%Y-%m-%d %H:%M:%S")
                    base=d/f"{dt.year:04d}"/f"{dt.month:02d}"
                else:
                    date_text=""
                    base=d/"촬영일_확인필요"
                    review+=1
                if duplicate and not self.dups.get():
                    rows.append([p.name,date_text,method,confidence,str(p),"","중복-건너뜀",seen[h],""])
                    dupc+=1
                else:
                    if duplicate: base=d/"중복검토"/(f"{dt.year:04d}" if dt else "촬영일_확인필요")/(f"{dt.month:02d}" if dt else "")
                    base.mkdir(parents=True,exist_ok=True)
                    out=unique_dest(base,p.name); shutil.copy2(p,out)
                    if p.stat().st_size != out.stat().st_size: raise IOError("복사 후 파일 크기 불일치")
                    rows.append([p.name,date_text,method,confidence,str(p),str(out),"중복-복사" if duplicate else ("확인필요" if not dt else "정상"),seen.get(h,""),""])
                    copied+=1
                    if duplicate: dupc+=1
                seen.setdefault(h,str(p))
            except Exception as e:
                errors+=1; rows.append([p.name,"","오류","확인필요",str(p),"","오류","",""+str(e)])
            if i%10==0 or i==total: self.q.put(("progress",i,f"{i:,}/{total:,} 처리 중 — {p.name}"))
        report=d/"사진정리_결과.csv"
        with open(report,"w",newline="",encoding="utf-8-sig") as f:
            w=csv.writer(f); w.writerow(["파일명","촬영일","날짜판정방식","신뢰도","원본경로","정리경로","중복여부/결과","중복원본","비고"]); w.writerows(rows)
        self.q.put(("done",f"완료: 복사 {copied:,}개 / 중복 {dupc:,}개 / 촬영일 확인필요 {review:,}개 / 오류 {errors:,}개\n결과표: {report}"))

    def poll(self):
        try:
            while True:
                x=self.q.get_nowait()
                if x[0]=="max": self.pb["maximum"]=x[1]
                elif x[0]=="progress": self.pb["value"]=x[1]; self.status.config(text=x[2])
                elif x[0]=="log": self.write(x[1])
                elif x[0]=="done":
                    self.write(x[1]); self.status.config(text="완료"); self.startb.config(state="normal"); messagebox.showinfo(APP,x[1])
        except queue.Empty: pass
        self.root.after(100,self.poll)

if __name__=="__main__":
    root=tk.Tk(); App(root); root.mainloop()
