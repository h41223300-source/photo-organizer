# -*- coding: utf-8 -*-
"""
iCloud 사진 5만장 자동 정리 프로그램
- 원본 폴더에서 사진/동영상을 읽어 촬영일 기준 YYYY\\MM으로 복사
- 원본은 절대 삭제/이동하지 않음
- 완전 동일 파일은 SHA-256으로 검출
- 중복은 '중복검토' 폴더로 복사하지 않고 CSV에 기록하여 안전하게 검토
- EXIF 촬영일을 우선 사용하고, 없으면 파일 수정일을 사용
"""

import csv
import hashlib
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

PHOTO_EXTS = {
    ".jpg", ".jpeg", ".heic", ".heif", ".png", ".gif", ".tif", ".tiff",
    ".bmp", ".webp", ".dng", ".raw", ".cr2", ".cr3", ".nef", ".arw",
    ".orf", ".rw2", ".raf", ".pef", ".srw", ".avif"
}
VIDEO_EXTS = {".mov", ".mp4", ".m4v", ".avi", ".mts", ".m2ts", ".3gp"}

def sha256_file(path, chunk=1024*1024):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def try_exif_date(path):
    # Pillow가 설치되어 있으면 EXIF 촬영일을 읽음.
    try:
        from PIL import Image, ExifTags
        with Image.open(path) as im:
            exif = im.getexif()
            if exif:
                wanted = {36867, 36868, 306}  # DateTimeOriginal, DateTimeDigitized, DateTime
                vals = []
                for k in wanted:
                    v = exif.get(k)
                    if v:
                        vals.append(str(v))
                for v in vals:
                    for fmt in ("%Y:%m:%d %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
                        try:
                            return datetime.strptime(v[:19], fmt)
                        except ValueError:
                            pass
    except Exception:
        pass
    return None

def capture_date(path):
    d = try_exif_date(path)
    if d:
        return d, "EXIF"
    try:
        return datetime.fromtimestamp(path.stat().st_mtime), "파일수정일"
    except Exception:
        return datetime.now(), "현재시각"

def unique_destination(dest_dir, name):
    p = dest_dir / name
    if not p.exists():
        return p
    stem, suffix = p.stem, p.suffix
    n = 1
    while True:
        q = dest_dir / f"{stem}_중복파일{n}{suffix}"
        if not q.exists():
            return q
        n += 1

class App:
    def __init__(self, root):
        self.root = root
        root.title("iCloud 사진 자동 정리")
        root.geometry("760x560")
        root.minsize(700, 520)

        self.src = tk.StringVar()
        self.dst = tk.StringVar()
        self.include_video = tk.BooleanVar(value=True)
        self.copy_duplicates = tk.BooleanVar(value=False)

        frame = ttk.Frame(root, padding=18)
        frame.pack(fill="both", expand=True)

        ttk.Label(frame, text="iCloud 사진 자동 정리", font=("Malgun Gothic", 18, "bold")).pack(anchor="w")
        ttk.Label(frame, text="원본은 건드리지 않고, 촬영일 기준으로 복사합니다.", foreground="#555").pack(anchor="w", pady=(2,15))

        self.row(frame, "① 원본 사진 폴더", self.src, self.choose_src)
        self.row(frame, "② 정리할 폴더", self.dst, self.choose_dst)

        opts = ttk.LabelFrame(frame, text="옵션", padding=10)
        opts.pack(fill="x", pady=12)
        ttk.Checkbutton(opts, text="동영상(MOV/MP4)도 함께 정리", variable=self.include_video).pack(anchor="w")
        ttk.Checkbutton(opts, text="완전 중복 파일을 별도 폴더에 복사 (권장: 처음에는 끄기)",
                        variable=self.copy_duplicates).pack(anchor="w", pady=(6,0))

        self.progress = ttk.Progressbar(frame, mode="determinate")
        self.progress.pack(fill="x", pady=(10,4))
        self.status = tk.StringVar(value="준비됨")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w")

        self.log = tk.Text(frame, height=15, wrap="word")
        self.log.pack(fill="both", expand=True, pady=10)

        self.start_btn = ttk.Button(frame, text="③ 정리 시작", command=self.start)
        self.start_btn.pack(fill="x", ipady=8)

    def row(self, parent, label, var, cmd):
        r = ttk.Frame(parent)
        r.pack(fill="x", pady=5)
        ttk.Label(r, text=label, width=20).pack(side="left")
        ttk.Entry(r, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(r, text="찾아보기", command=cmd).pack(side="left", padx=(8,0))

    def choose_src(self):
        p = filedialog.askdirectory(title="iCloud 사진 원본 폴더를 선택하세요")
        if p: self.src.set(p)

    def choose_dst(self):
        p = filedialog.askdirectory(title="정리된 사진을 저장할 폴더를 선택하세요")
        if p: self.dst.set(p)

    def logmsg(self, s):
        self.root.after(0, lambda: (self.log.insert("end", s + "\n"), self.log.see("end")))

    def start(self):
        src = Path(self.src.get())
        dst = Path(self.dst.get())
        if not src.is_dir():
            messagebox.showwarning("확인", "① 원본 사진 폴더를 먼저 선택하세요.")
            return
        if not str(dst):
            messagebox.showwarning("확인", "② 정리할 폴더를 선택하세요.")
            return
        if src.resolve() == dst.resolve():
            messagebox.showwarning("확인", "원본 폴더와 정리 폴더는 다르게 선택하세요.")
            return

        dst.mkdir(parents=True, exist_ok=True)
        self.start_btn.config(state="disabled")
        self.log.delete("1.0", "end")
        threading.Thread(target=self.run, args=(src,dst), daemon=True).start()

    def run(self, src, dst):
        try:
            exts = PHOTO_EXTS | (VIDEO_EXTS if self.include_video.get() else set())
            files = [p for p in src.rglob("*") if p.is_file() and p.suffix.lower() in exts]
            total = len(files)
            self.root.after(0, lambda: self.progress.config(maximum=max(total,1), value=0))
            self.logmsg(f"찾은 파일: {total:,}개")
            self.logmsg("원본은 삭제하거나 이동하지 않습니다.")
            self.logmsg("중복 검사를 시작합니다...")

            hashes = {}
            duplicates = []
            copied = 0
            errors = 0
            rows = []

            for i, p in enumerate(files, 1):
                try:
                    h = sha256_file(p)
                    duplicate_of = hashes.get(h)
                    if duplicate_of:
                        duplicates.append((p, duplicate_of, h))
                        if self.copy_duplicates.get():
                            dd = dst / "중복검토"
                            dd.mkdir(parents=True, exist_ok=True)
                            target = unique_destination(dd, p.name)
                            shutil.copy2(p, target)
                            dest_str = str(target)
                        else:
                            dest_str = ""
                        d, source = capture_date(p)
                        rows.append([str(p), dest_str, d.strftime("%Y-%m-%d %H:%M:%S"), source, h, "완전중복", str(duplicate_of)])
                    else:
                        hashes[h] = p
                        d, source = capture_date(p)
                        month_dir = dst / f"{d.year:04d}" / f"{d.month:02d}"
                        month_dir.mkdir(parents=True, exist_ok=True)
                        target = unique_destination(month_dir, p.name)
                        shutil.copy2(p, target)
                        copied += 1
                        rows.append([str(p), str(target), d.strftime("%Y-%m-%d %H:%M:%S"), source, h, "고유파일", ""])
                except Exception as e:
                    errors += 1
                    rows.append([str(p), "", "", "", "", "오류", repr(e)])

                if i % 25 == 0 or i == total:
                    self.root.after(0, lambda v=i: self.progress.config(value=v))
                    self.root.after(0, lambda v=i: self.status.set(f"처리 중: {v:,} / {total:,}"))
                    if i % 500 == 0:
                        self.logmsg(f"{i:,} / {total:,} 처리 완료")

            report = dst / "사진정리_결과.csv"
            with open(report, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.writer(f)
                w.writerow(["원본경로","정리파일경로","촬영일","날짜출처","SHA-256","분류","동일원본"])
                w.writerows(rows)

            summary = (
                f"정리 완료\n\n"
                f"전체 파일: {total:,}개\n"
                f"정리된 고유 파일: {copied:,}개\n"
                f"완전 중복: {len(duplicates):,}개\n"
                f"오류: {errors:,}개\n\n"
                f"결과 폴더:\n{dst}\n\n"
                f"상세 보고서:\n{report}"
            )
            self.logmsg("")
            self.logmsg("===== 완료 =====")
            self.logmsg(summary)
            self.root.after(0, lambda: self.status.set("완료"))
            self.root.after(0, lambda: messagebox.showinfo("완료", summary))
        except Exception as e:
            self.logmsg("오류: " + repr(e))
            self.root.after(0, lambda: messagebox.showerror("오류", str(e)))
        finally:
            self.root.after(0, lambda: self.start_btn.config(state="normal"))

if __name__ == "__main__":
    root = tk.Tk()
    try:
        from tkinter import ttk
    except Exception:
        pass
    App(root)
    root.mainloop()
