import os, re, csv, shutil, hashlib, subprocess, threading, queue, sys
from pathlib import Path
from datetime import datetime, timezone
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP='사진관리 V2'
IMAGE_EXT={'.jpg','.jpeg','.png','.gif','.tif','.tiff','.bmp','.webp','.heic','.heif','.avif','.dng','.raw','.cr2','.cr3','.nef','.arw','.orf','.rw2','.raf','.pef','.srw'}
VIDEO_EXT={'.mov','.mp4','.m4v','.avi','.mts','.m2ts','.3gp'}
DATE_TAGS=['DateTimeOriginal','CreateDate','DateTimeDigitized','MediaCreateDate','TrackCreateDate','CreationDate','QuickTime:CreateDate','DateTime']
FILENAME_PATTERNS=[
    re.compile(r'(?<!\d)(20\d{2}|19\d{2})[-_.]?(0[1-9]|1[0-2])[-_.]?([0-2]\d|3[01])(?:[-_ T]?(?:[0-2]\d)[-_.:]?(?:[0-5]\d)[-_.:]?(?:[0-5]\d))?'),
]

def resource_path(name):
    base=getattr(sys,'_MEIPASS',os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base,name)

def exiftool_path():
    for n in ('exiftool.exe','exiftool(-k).exe','exiftool'):
        p=resource_path(n)
        if os.path.exists(p): return p
    return shutil.which('exiftool')

def parse_dt(s):
    if not s: return None
    s=str(s).strip().replace('Z','+00:00')
    s=re.sub(r'^(\d{4}):(\d{2}):(\d{2})',r'\1-\2-\3',s)
    for fmt in ('%Y-%m-%d %H:%M:%S%z','%Y-%m-%d %H:%M:%S','%Y-%m-%dT%H:%M:%S%z','%Y-%m-%dT%H:%M:%S','%Y-%m-%d'):
        try:
            d=datetime.strptime(s[:25],fmt)
            if d.tzinfo: d=d.astimezone().replace(tzinfo=None)
            if 1900 <= d.year <= datetime.now().year+1: return d
        except: pass
    m=re.search(r'(19\d{2}|20\d{2})[-:]?(0[1-9]|1[0-2])[-:]?([0-2]\d|3[01])(?:[ T](\d{2}):?(\d{2}):?(\d{2}))?',s)
    if m:
        try: return datetime(int(m[1]),int(m[2]),int(m[3]),int(m[4] or 0),int(m[5] or 0),int(m[6] or 0))
        except: return None
    return None

def metadata_date(path):
    tool=exiftool_path()
    if tool:
        args=[tool,'-s3','-api','QuickTimeUTC=1']
        for t in DATE_TAGS: args += ['-'+t]
        args += [str(path)]
        try:
            r=subprocess.run(args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20,creationflags=(subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0))
            vals=[x.strip() for x in r.stdout.splitlines()]
            for tag,val in zip(DATE_TAGS,vals):
                d=parse_dt(val)
                if d: return d, '메타데이터:'+tag
        except: pass
    # Pillow fallback, including ExifIFD
    if path.suffix.lower() in IMAGE_EXT:
        try:
            from PIL import Image, ExifTags
            with Image.open(path) as im:
                ex=im.getexif()
                candidates=[]
                for k,v in ex.items():
                    name=ExifTags.TAGS.get(k,str(k))
                    if name in ('DateTimeOriginal','DateTimeDigitized','DateTime'): candidates.append((name,v))
                try:
                    sub=ex.get_ifd(0x8769)
                    for k,v in sub.items():
                        name=ExifTags.TAGS.get(k,str(k))
                        if name in ('DateTimeOriginal','DateTimeDigitized','DateTime'): candidates.insert(0,(name,v))
                except: pass
                priority={'DateTimeOriginal':0,'DateTimeDigitized':1,'DateTime':2}
                candidates.sort(key=lambda x:priority.get(x[0],9))
                for name,v in candidates:
                    d=parse_dt(v)
                    if d: return d,'EXIF:'+name
        except: pass
    for pat in FILENAME_PATTERNS:
        m=pat.search(path.stem)
        if m:
            try: return datetime(int(m[1]),int(m[2]),int(m[3])), '파일명 날짜'
            except: pass
    return datetime.fromtimestamp(path.stat().st_mtime), '파일 수정일(최후수단)'

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
        q=folder/f'{stem}_{i}{suf}'
        if not q.exists(): return q
        i+=1

def same_path(a,b):
    try: return os.path.samefile(a,b)
    except: return os.path.abspath(a).lower()==os.path.abspath(b).lower()

class App:
    def __init__(self,root):
        self.root=root; root.title(APP); root.geometry('760x520')
        self.src=tk.StringVar(); self.dst=tk.StringVar(); self.videos=tk.BooleanVar(value=True); self.dups=tk.BooleanVar(value=False)
        self.q=queue.Queue(); self.stop=False
        f=ttk.Frame(root,padding=14); f.pack(fill='both',expand=True)
        ttk.Label(f,text='원본 폴더 (읽기만 함)').grid(row=0,column=0,sticky='w')
        ttk.Entry(f,textvariable=self.src,width=72).grid(row=1,column=0,sticky='ew',padx=(0,8)); ttk.Button(f,text='찾아보기',command=lambda:self.pick(self.src)).grid(row=1,column=1)
        ttk.Label(f,text='정리본 저장 폴더').grid(row=2,column=0,sticky='w',pady=(12,0))
        ttk.Entry(f,textvariable=self.dst,width=72).grid(row=3,column=0,sticky='ew',padx=(0,8)); ttk.Button(f,text='찾아보기',command=lambda:self.pick(self.dst)).grid(row=3,column=1)
        ttk.Checkbutton(f,text='동영상도 정리 (MOV/MP4 등)',variable=self.videos).grid(row=4,column=0,sticky='w',pady=(12,0))
        ttk.Checkbutton(f,text='완전 동일 중복파일도 중복검토 폴더에 복사',variable=self.dups).grid(row=5,column=0,sticky='w')
        ttk.Label(f,text='정리 기준: 촬영 메타데이터 → 파일명 날짜 → 수정일(최후수단) / 원본은 삭제·이동하지 않습니다.').grid(row=6,column=0,columnspan=2,sticky='w',pady=(10,4))
        self.pb=ttk.Progressbar(f,mode='determinate'); self.pb.grid(row=7,column=0,columnspan=2,sticky='ew',pady=8)
        self.status=ttk.Label(f,text='준비됨'); self.status.grid(row=8,column=0,columnspan=2,sticky='w')
        self.log=tk.Text(f,height=14,state='disabled'); self.log.grid(row=9,column=0,columnspan=2,sticky='nsew',pady=(8,8))
        bf=ttk.Frame(f); bf.grid(row=10,column=0,columnspan=2,sticky='e')
        self.startb=ttk.Button(bf,text='정리 시작',command=self.start); self.startb.pack(side='left',padx=4)
        ttk.Button(bf,text='종료',command=root.destroy).pack(side='left')
        f.columnconfigure(0,weight=1); f.rowconfigure(9,weight=1)
        root.after(100,self.poll)
    def pick(self,var):
        p=filedialog.askdirectory()
        if p: var.set(p)
    def write(self,s):
        self.log.configure(state='normal'); self.log.insert('end',s+'\n'); self.log.see('end'); self.log.configure(state='disabled')
    def start(self):
        s,d=Path(self.src.get()),Path(self.dst.get())
        if not s.is_dir(): return messagebox.showerror(APP,'원본 폴더를 선택하세요.')
        if not self.dst.get(): return messagebox.showerror(APP,'정리본 저장 폴더를 선택하세요.')
        d.mkdir(parents=True,exist_ok=True)
        try:
            if same_path(s,d) or str(d.resolve()).lower().startswith(str(s.resolve()).lower()+os.sep):
                return messagebox.showerror(APP,'정리본 폴더는 원본 폴더 내부가 아닌 별도 위치를 선택하세요.')
        except: pass
        self.startb.config(state='disabled'); self.pb['value']=0; self.write('검사를 시작합니다...')
        threading.Thread(target=self.worker,args=(s,d),daemon=True).start()
    def worker(self,s,d):
        exts=set(IMAGE_EXT)|(VIDEO_EXT if self.videos.get() else set())
        files=[p for p in s.rglob('*') if p.is_file() and p.suffix.lower() in exts]
        total=len(files); seen={}; rows=[]; copied=dupc=errors=0
        self.q.put(('max',max(total,1))); self.q.put(('log',f'대상 파일: {total:,}개'))
        for i,p in enumerate(files,1):
            try:
                dt,method=metadata_date(p); h=sha256(p); duplicate=h in seen
                if duplicate and not self.dups.get():
                    rows.append([p.name,dt.strftime('%Y-%m-%d %H:%M:%S'),method,str(p),'', '중복-건너뜀',seen[h]])
                    dupc+=1
                else:
                    base=d/('중복검토' if duplicate else '')/f'{dt.year:04d}'/f'{dt.month:02d}'
                    base.mkdir(parents=True,exist_ok=True); out=unique_dest(base,p.name)
                    shutil.copy2(p,out)
                    if p.stat().st_size != out.stat().st_size: raise IOError('복사 후 파일 크기 불일치')
                    rows.append([p.name,dt.strftime('%Y-%m-%d %H:%M:%S'),method,str(p),str(out),'중복-복사' if duplicate else '정상',''])
                    copied+=1; dupc+=1 if duplicate else 0
                seen.setdefault(h,str(p))
            except Exception as e:
                errors+=1; rows.append([p.name,'','오류',str(p),'','오류',str(e)])
            if i%10==0 or i==total: self.q.put(('progress',i,f'{i:,}/{total:,} 처리 중 — {p.name}'))
        report=d/'사진정리_결과.csv'
        with open(report,'w',newline='',encoding='utf-8-sig') as f:
            w=csv.writer(f); w.writerow(['파일명','촬영일','날짜판정방식','원본경로','정리경로','중복여부/결과','비고']); w.writerows(rows)
        self.q.put(('done',f'완료: 복사 {copied:,}개 / 중복 {dupc:,}개 / 오류 {errors:,}개\n결과표: {report}'))
    def poll(self):
        try:
            while True:
                x=self.q.get_nowait()
                if x[0]=='max': self.pb['maximum']=x[1]
                elif x[0]=='progress': self.pb['value']=x[1]; self.status.config(text=x[2])
                elif x[0]=='log': self.write(x[1])
                elif x[0]=='done': self.write(x[1]); self.status.config(text='완료'); self.startb.config(state='normal'); messagebox.showinfo(APP,x[1])
        except queue.Empty: pass
        self.root.after(100,self.poll)

if __name__=='__main__':
    root=tk.Tk(); App(root); root.mainloop()
