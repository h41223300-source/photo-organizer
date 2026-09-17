import os
import re
import csv
import json
import shutil
import hashlib
import subprocess
import threading
import queue
import sys

from pathlib import Path
from datetime import datetime
import tkinter as tk
from tkinter import ttk, filedialog, messagebox


APP = "사진관리 V2.2 - 촬영일 정밀판정"

IMAGE_EXT = {
    ".jpg", ".jpeg", ".png", ".gif", ".tif", ".tiff",
    ".bmp", ".webp", ".heic", ".heif", ".avif",
    ".dng", ".raw", ".cr2", ".cr3", ".nef", ".arw",
    ".orf", ".rw2", ".raf", ".pef", ".srw"
}

VIDEO_EXT = {
    ".mov", ".mp4", ".m4v", ".avi",
    ".mts", ".m2ts", ".3gp"
}

# 실제 촬영일로 우선 인정할 태그
PHOTO_PRIORITY = [
    "DateTimeOriginal",
    "DateTimeDigitized",
    "CreateDate",
    "DateTime"
]

VIDEO_PRIORITY = [
    "CreationDate",
    "CreateDate",
    "MediaCreateDate",
    "TrackCreateDate"
]


# ---------------------------------------------------------
# PyInstaller / ExifTool
# ---------------------------------------------------------

def resource_path(name):
    base = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(base, name)


def exiftool_path():
    candidates = [
        resource_path("exiftool.exe"),
        resource_path("exiftool(-k).exe")
    ]

    for p in candidates:
        if os.path.exists(p):
            return p

    return shutil.which("exiftool")


def exiftool_status():
    tool = exiftool_path()

    if not tool:
        return False, "", "ExifTool 실행파일을 찾을 수 없습니다."

    try:
        flags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        )

        r = subprocess.run(
            [tool, "-ver"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            creationflags=flags
        )

        if r.returncode == 0 and r.stdout.strip():
            return True, tool, r.stdout.strip()

        return (
            False,
            tool,
            (r.stderr or r.stdout or "ExifTool 실행 실패").strip()
        )

    except Exception as e:
        return False, tool, str(e)


# ---------------------------------------------------------
# 날짜 파싱
# ---------------------------------------------------------

def parse_dt(value):
    if value is None:
        return None

    s = str(value).strip()

    if not s:
        return None

    # 2017:06:10 18:32:21
    # 2017-06-10 18:32:21
    # 2017:06:10 18:32:21+09:00
    # 2017-06-10T18:32:21
    m = re.search(
        r"(?<!\d)"
        r"(19\d{2}|20\d{2})"
        r"[:-](0[1-9]|1[0-2])"
        r"[:-]([0-2]\d|3[01])"
        r"(?:[ T]"
        r"([0-2]\d)"
        r"[:.]?([0-5]\d)"
        r"[:.]?([0-5]\d))?",
        s
    )

    if m:
        try:
            y = int(m.group(1))
            mo = int(m.group(2))
            d = int(m.group(3))
            h = int(m.group(4) or 0)
            mi = int(m.group(5) or 0)
            sec = int(m.group(6) or 0)

            dt = datetime(y, mo, d, h, mi, sec)

            if 1900 <= dt.year <= datetime.now().year + 1:
                return dt

        except Exception:
            pass

    # YYYYMMDD 또는 YYYYMMDD_HHMMSS
    m = re.search(
        r"(?<!\d)"
        r"(19\d{2}|20\d{2})"
        r"(0[1-9]|1[0-2])"
        r"([0-2]\d|3[01])"
        r"(?:[_\- ]?"
        r"([0-2]\d)"
        r"([0-5]\d)"
        r"([0-5]\d))?"
        r"(?!\d)",
        s
    )

    if m:
        try:
            return datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4) or 0),
                int(m.group(5) or 0),
                int(m.group(6) or 0)
            )
        except Exception:
            pass

    return None


# ---------------------------------------------------------
# ExifTool JSON
# ---------------------------------------------------------

def read_exiftool(path):
    tool = exiftool_path()

    if not tool:
        return {}, "ExifTool 없음"

    flags = (
        subprocess.CREATE_NO_WINDOW
        if os.name == "nt"
        else 0
    )

    # -G1: 그룹명 표시
    # -a : 중복 태그 허용
    # -s : 짧은 태그명
    # -j : JSON
    args = [
        tool,
        "-j",
        "-G1",
        "-a",
        "-s",
        "-charset",
        "filename=UTF8",
        str(path)
    ]

    try:
        r = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=flags
        )

        if r.returncode != 0:
            err = (
                r.stderr.strip()
                or r.stdout.strip()
                or f"ExifTool 종료코드 {r.returncode}"
            )
            return {}, err

        if not r.stdout.strip():
            return {}, "ExifTool 출력 없음"

        data = json.loads(r.stdout)

        if not isinstance(data, list) or not data:
            return {}, "ExifTool JSON 결과 없음"

        return data[0], ""

    except subprocess.TimeoutExpired:
        return {}, "ExifTool 시간초과"

    except Exception as e:
        return {}, f"ExifTool 오류: {e}"


def short_tag(key):
    return str(key).split(":")[-1]


def collect_date_tags(metadata):
    result = []

    for key, value in metadata.items():
        tag = short_tag(key)

        # 날짜로 보이는 태그만 진단 기록
        if (
            "date" in tag.lower()
            or "time" in tag.lower()
        ):
            dt = parse_dt(value)

            if dt:
                result.append(
                    (key, str(value), dt)
                )

    return result


def find_priority_tag(metadata, priority):
    date_tags = collect_date_tags(metadata)

    for wanted in priority:
        for key, raw, dt in date_tags:
            if short_tag(key).lower() == wanted.lower():
                return dt, key, raw

    return None, "", ""


# ---------------------------------------------------------
# Pillow EXIF 보조
# ---------------------------------------------------------

def pillow_date(path):
    if path.suffix.lower() not in IMAGE_EXT:
        return None, ""

    try:
        from PIL import Image, ExifTags

        with Image.open(path) as im:
            exif = im.getexif()

            if not exif:
                return None, ""

            found = []

            for k, v in exif.items():
                name = ExifTags.TAGS.get(k, str(k))

                if name in (
                    "DateTimeOriginal",
                    "DateTimeDigitized",
                    "DateTime"
                ):
                    dt = parse_dt(v)

                    if dt:
                        found.append((name, dt))

            # 중요: nested ExifIFD
            try:
                sub = exif.get_ifd(0x8769)

                for k, v in sub.items():
                    name = ExifTags.TAGS.get(k, str(k))

                    if name in (
                        "DateTimeOriginal",
                        "DateTimeDigitized",
                        "DateTime"
                    ):
                        dt = parse_dt(v)

                        if dt:
                            found.append((name, dt))
            except Exception:
                pass

            priority = {
                "DateTimeOriginal": 0,
                "DateTimeDigitized": 1,
                "DateTime": 2
            }

            found.sort(
                key=lambda x: priority.get(x[0], 99)
            )

            if found:
                return found[0][1], found[0][0]

    except Exception:
        pass

    return None, ""


# ---------------------------------------------------------
# 파일명 날짜
# ---------------------------------------------------------

def filename_date(path):
    name = path.stem

    # 20240115 / 20240115_143025
    # 2024-01-15 / 2024_01_15
    patterns = [
        re.compile(
            r"(?<!\d)"
            r"(19\d{2}|20\d{2})"
            r"[-_.]?"
            r"(0[1-9]|1[0-2])"
            r"[-_.]?"
            r"([0-2]\d|3[01])"
            r"(?:[-_ T]?"
            r"([0-2]\d)"
            r"[-_.:]?"
            r"([0-5]\d)"
            r"[-_.:]?"
            r"([0-5]\d))?"
        )
    ]

    for pat in patterns:
        m = pat.search(name)

        if not m:
            continue

        try:
            return datetime(
                int(m.group(1)),
                int(m.group(2)),
                int(m.group(3)),
                int(m.group(4) or 0),
                int(m.group(5) or 0),
                int(m.group(6) or 0)
            )
        except Exception:
            pass

    return None


# ---------------------------------------------------------
# 촬영일 최종 판정
# ---------------------------------------------------------

def determine_capture_date(path):
    ext = path.suffix.lower()

    metadata, exif_error = read_exiftool(path)

    diagnostics = []

    if metadata:
        for key, raw, dt in collect_date_tags(metadata):
            diagnostics.append(
                f"{key}={raw}"
            )

    # 사진
    if ext in IMAGE_EXT:
        dt, tag, raw = find_priority_tag(
            metadata,
            PHOTO_PRIORITY
        )

        if dt:
            return {
                "date": dt,
                "method": f"ExifTool:{tag}",
                "confidence": "확정",
                "folder_ok": True,
                "note": "",
                "diagnostic": " | ".join(diagnostics),
                "exif_error": exif_error
            }

        # ExifTool이 못 읽더라도 Pillow로 한 번 더
        dt, tag = pillow_date(path)

        if dt:
            return {
                "date": dt,
                "method": f"EXIF:{tag}",
                "confidence": "확정",
                "folder_ok": True,
                "note": "Pillow EXIF 보조판독",
                "diagnostic": " | ".join(diagnostics),
                "exif_error": exif_error
            }

    # 동영상
    if ext in VIDEO_EXT:
        dt, tag, raw = find_priority_tag(
            metadata,
            VIDEO_PRIORITY
        )

        if dt:
            return {
                "date": dt,
                "method": f"ExifTool:{tag}",
                "confidence": "확정",
                "folder_ok": True,
                "note": "",
                "diagnostic": " | ".join(diagnostics),
                "exif_error": exif_error
            }

    # 메타데이터에 실제 촬영일이 없으면 파일명 검사
    fn = filename_date(path)

    if fn:
        return {
            "date": fn,
            "method": "파일명 날짜",
            "confidence": "보조",
            "folder_ok": True,
            "note": "촬영일 메타데이터 없음",
            "diagnostic": " | ".join(diagnostics),
            "exif_error": exif_error
        }

    # 수정일은 CSV 참고용으로만 기록
    modified = datetime.fromtimestamp(
        path.stat().st_mtime
    )

    return {
        "date": modified,
        "method": "파일 수정일(참고용)",
        "confidence": "확인필요",
        "folder_ok": False,
        "note": "실제 촬영일을 확정하지 못함",
        "diagnostic": " | ".join(diagnostics),
        "exif_error": exif_error
    }


# ---------------------------------------------------------
# 중복 검사
# ---------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for b in iter(
            lambda: f.read(4 * 1024 * 1024),
            b""
        ):
            h.update(b)

    return h.hexdigest()


def unique_dest(folder, name):
    p = folder / name

    if not p.exists():
        return p

    stem = Path(name).stem
    suffix = Path(name).suffix

    i = 2

    while True:
        q = folder / f"{stem}_{i}{suffix}"

        if not q.exists():
            return q

        i += 1


def same_path(a, b):
    try:
        return os.path.samefile(a, b)
    except Exception:
        return (
            os.path.abspath(a).lower()
            ==
            os.path.abspath(b).lower()
        )


# ---------------------------------------------------------
# GUI
# ---------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root

        root.title(APP)
        root.geometry("850x620")

        self.src = tk.StringVar()
        self.dst = tk.StringVar()

        self.videos = tk.BooleanVar(value=True)
        self.dups = tk.BooleanVar(value=False)

        self.q = queue.Queue()

        f = ttk.Frame(root, padding=14)
        f.pack(fill="both", expand=True)

        ttk.Label(
            f,
            text="원본 폴더 (읽기만 함)"
        ).grid(row=0, column=0, sticky="w")

        ttk.Entry(
            f,
            textvariable=self.src,
            width=75
        ).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(0, 8)
        )

        ttk.Button(
            f,
            text="찾아보기",
            command=lambda: self.pick(self.src)
        ).grid(row=1, column=1)

        ttk.Label(
            f,
            text="정리본 저장 폴더"
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(12, 0)
        )

        ttk.Entry(
            f,
            textvariable=self.dst,
            width=75
        ).grid(
            row=3,
            column=0,
            sticky="ew",
            padx=(0, 8)
        )

        ttk.Button(
            f,
            text="찾아보기",
            command=lambda: self.pick(self.dst)
        ).grid(row=3, column=1)

        ttk.Checkbutton(
            f,
            text="동영상도 정리 (MOV/MP4 등)",
            variable=self.videos
        ).grid(
            row=4,
            column=0,
            sticky="w",
            pady=(12, 0)
        )

        ttk.Checkbutton(
            f,
            text="완전 동일 중복파일도 중복검토 폴더에 복사",
            variable=self.dups
        ).grid(
            row=5,
            column=0,
            sticky="w"
        )

        ttk.Label(
            f,
            text=(
                "V2.2: 촬영 메타데이터 → 파일명 날짜 순으로 판정 / "
                "촬영일을 확정할 수 없는 파일은 '촬영일_확인필요' 폴더로 분리"
            )
        ).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(10, 2)
        )

        ttk.Label(
            f,
            text=(
                "※ 파일 수정일은 연/월 분류에 사용하지 않습니다. "
                "원본은 삭제·이동하지 않고 복사만 합니다."
            )
        ).grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="w"
        )

        self.pb = ttk.Progressbar(
            f,
            mode="determinate"
        )

        self.pb.grid(
            row=8,
            column=0,
            columnspan=2,
            sticky="ew",
            pady=8
        )

        self.status = ttk.Label(
            f,
            text="준비됨"
        )

        self.status.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="w"
        )

        self.log = tk.Text(
            f,
            height=17,
            state="disabled"
        )

        self.log.grid(
            row=10,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(8, 8)
        )

        bf = ttk.Frame(f)

        bf.grid(
            row=11,
            column=0,
            columnspan=2,
            sticky="e"
        )

        self.startb = ttk.Button(
            bf,
            text="정리 시작",
            command=self.start
        )

        self.startb.pack(
            side="left",
            padx=4
        )

        ttk.Button(
            bf,
            text="종료",
            command=root.destroy
        ).pack(side="left")

        f.columnconfigure(0, weight=1)
        f.rowconfigure(10, weight=1)

        # 시작할 때 ExifTool 자체 점검
        root.after(300, self.check_tool)
        root.after(100, self.poll)


    def check_tool(self):
        ok, path, info = exiftool_status()

        if ok:
            self.write(
                f"ExifTool 정상 실행 / 버전 {info}"
            )
            self.write(
                f"ExifTool 위치: {path}"
            )
        else:
            self.write(
                "경고: ExifTool 정상 실행 실패"
            )
            self.write(
                f"내용: {info}"
            )


    def pick(self, var):
        p = filedialog.askdirectory()

        if p:
            var.set(p)


    def write(self, s):
        self.log.configure(state="normal")
        self.log.insert("end", s + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


    def start(self):
        s = Path(self.src.get())
        d = Path(self.dst.get())

        if not s.is_dir():
            return messagebox.showerror(
                APP,
                "원본 폴더를 선택하세요."
            )

        if not self.dst.get():
            return messagebox.showerror(
                APP,
                "정리본 저장 폴더를 선택하세요."
            )

        d.mkdir(
            parents=True,
            exist_ok=True
        )

        try:
            if (
                same_path(s, d)
                or str(d.resolve()).lower().startswith(
                    str(s.resolve()).lower() + os.sep
                )
            ):
                return messagebox.showerror(
                    APP,
                    "정리본 폴더는 원본 폴더 내부가 아닌 "
                    "별도 위치를 선택하세요."
                )
        except Exception:
            pass

        self.startb.config(
            state="disabled"
        )

        self.pb["value"] = 0

        self.write(
            "V2.2 촬영일 정밀 검사를 시작합니다..."
        )

        threading.Thread(
            target=self.worker,
            args=(s, d),
            daemon=True
        ).start()


    def worker(self, s, d):
        exts = set(IMAGE_EXT)

        if self.videos.get():
            exts |= VIDEO_EXT

        files = [
            p for p in s.rglob("*")
            if p.is_file()
            and p.suffix.lower() in exts
        ]

        total = len(files)

        seen = {}
        rows = []

        copied = 0
        dupc = 0
        errors = 0
        confirm = 0
        metadata_ok = 0
        filename_ok = 0

        self.q.put(
            ("max", max(total, 1))
        )

        self.q.put(
            ("log", f"대상 파일: {total:,}개")
        )

        for i, p in enumerate(files, 1):

            try:
                result = determine_capture_date(p)

                dt = result["date"]
                method = result["method"]
                confidence = result["confidence"]
                folder_ok = result["folder_ok"]
                note = result["note"]
                diagnostic = result["diagnostic"]
                exif_error = result["exif_error"]

                if method.startswith("ExifTool") or method.startswith("EXIF"):
                    metadata_ok += 1

                elif method == "파일명 날짜":
                    filename_ok += 1

                if confidence == "확인필요":
                    confirm += 1

                h = sha256(p)
                duplicate = h in seen

                if duplicate and not self.dups.get():

                    rows.append([
                        p.name,
                        dt.strftime("%Y-%m-%d %H:%M:%S"),
                        method,
                        confidence,
                        str(p),
                        "",
                        "중복-건너뜀",
                        seen[h],
                        note,
                        exif_error,
                        diagnostic
                    ])

                    dupc += 1

                else:
                    if folder_ok:
                        base = (
                            d
                            / f"{dt.year:04d}"
                            / f"{dt.month:02d}"
                        )
                    else:
                        base = (
                            d
                            / "촬영일_확인필요"
                        )

                    if duplicate:
                        base = (
                            d
                            / "중복검토"
                            / (
                                f"{dt.year:04d}"
                                if folder_ok
                                else "촬영일_확인필요"
                            )
                            / (
                                f"{dt.month:02d}"
                                if folder_ok
                                else ""
                            )
                        )

                    base.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    out = unique_dest(
                        base,
                        p.name
                    )

                    shutil.copy2(
                        p,
                        out
                    )

                    if (
                        p.stat().st_size
                        != out.stat().st_size
                    ):
                        raise IOError(
                            "복사 후 파일 크기 불일치"
                        )

                    rows.append([
                        p.name,
                        dt.strftime("%Y-%m-%d %H:%M:%S"),
                        method,
                        confidence,
                        str(p),
                        str(out),
                        (
                            "중복-복사"
                            if duplicate
                            else "정상"
                        ),
                        "",
                        note,
                        exif_error,
                        diagnostic
                    ])

                    copied += 1

                    if duplicate:
                        dupc += 1

                seen.setdefault(
                    h,
                    str(p)
                )

            except Exception as e:
                errors += 1

                rows.append([
                    p.name,
                    "",
                    "오류",
                    "",
                    str(p),
                    "",
                    "오류",
                    "",
                    str(e),
                    "",
                    ""
                ])

            if i % 10 == 0 or i == total:
                self.q.put(
                    (
                        "progress",
                        i,
                        f"{i:,}/{total:,} 처리 중 — {p.name}"
                    )
                )

        report = d / "사진정리_결과_V2.2.csv"

        with open(
            report,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            w = csv.writer(f)

            w.writerow([
                "파일명",
                "판정날짜",
                "날짜판정방식",
                "신뢰도",
                "원본경로",
                "정리경로",
                "중복여부/결과",
                "중복원본",
                "비고",
                "ExifTool오류",
                "메타데이터진단"
            ])

            w.writerows(rows)

        result_text = (
            f"V2.2 완료\n\n"
            f"전체 대상: {total:,}개\n"
            f"복사: {copied:,}개\n"
            f"메타데이터 촬영일: {metadata_ok:,}개\n"
            f"파일명 날짜: {filename_ok:,}개\n"
            f"촬영일 확인필요: {confirm:,}개\n"
            f"중복: {dupc:,}개\n"
            f"오류: {errors:,}개\n\n"
            f"결과표:\n{report}"
        )

        self.q.put(
            ("done", result_text)
        )


    def poll(self):
        try:
            while True:
                x = self.q.get_nowait()

                if x[0] == "max":
                    self.pb["maximum"] = x[1]

                elif x[0] == "progress":
                    self.pb["value"] = x[1]
                    self.status.config(
                        text=x[2]
                    )

                elif x[0] == "log":
                    self.write(x[1])

                elif x[0] == "done":
                    self.write(x[1])
                    self.status.config(
                        text="완료"
                    )
                    self.startb.config(
                        state="normal"
                    )
                    messagebox.showinfo(
                        APP,
                        x[1]
                    )

        except queue.Empty:
            pass

        self.root.after(
            100,
            self.poll
        )


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
