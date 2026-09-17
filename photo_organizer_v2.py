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


APP = "사진관리 V2.1 - 촬영일 우선 정리"

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


# ----------------------------------------------------------
# PyInstaller 내부 파일 위치
# ----------------------------------------------------------

def resource_path(name):
    base = getattr(
        sys,
        "_MEIPASS",
        os.path.dirname(os.path.abspath(__file__))
    )
    return os.path.join(base, name)


def exiftool_path():
    for name in (
        "exiftool.exe",
        "exiftool(-k).exe",
        "exiftool"
    ):
        p = resource_path(name)

        if os.path.exists(p):
            return p

    return shutil.which("exiftool")


# ----------------------------------------------------------
# 날짜 파싱
# ----------------------------------------------------------

def parse_dt(value):
    if not value:
        return None

    s = str(value).strip()

    if not s:
        return None

    # ExifTool 형식
    # 2017:06:10 18:32:21
    # 2017:06:10 18:32:21+09:00
    # 2017:06:10 18:32:21.123
    # 2017-06-10T18:32:21+09:00

    m = re.search(
        r"(19\d{2}|20\d{2})"
        r"[:-](0[1-9]|1[0-2])"
        r"[:-]([0-2]\d|3[01])"
        r"(?:[ T]"
        r"([0-2]\d)"
        r"[:]?([0-5]\d)"
        r"[:]?([0-5]\d))?",
        s
    )

    if not m:
        # YYYYMMDD
        m = re.search(
            r"(?<!\d)"
            r"(19\d{2}|20\d{2})"
            r"(0[1-9]|1[0-2])"
            r"([0-2]\d|3[01])"
            r"(?!\d)",
            s
        )

    if not m:
        return None

    try:
        year = int(m.group(1))
        month = int(m.group(2))
        day = int(m.group(3))

        hour = int(m.group(4)) if m.lastindex and m.lastindex >= 4 and m.group(4) else 0
        minute = int(m.group(5)) if m.lastindex and m.lastindex >= 5 and m.group(5) else 0
        second = int(m.group(6)) if m.lastindex and m.lastindex >= 6 and m.group(6) else 0

        now_year = datetime.now().year

        if year < 1900 or year > now_year + 1:
            return None

        return datetime(
            year,
            month,
            day,
            hour,
            minute,
            second
        )

    except Exception:
        return None


# ----------------------------------------------------------
# ExifTool JSON 메타데이터 읽기
# ----------------------------------------------------------

def read_metadata(path):
    tool = exiftool_path()

    if not tool:
        return {}

    args = [
        tool,
        "-j",
        "-G1",
        "-a",
        "-s",

        "-DateTimeOriginal",
        "-DateTimeDigitized",
        "-CreateDate",
        "-ModifyDate",
        "-DateTime",

        "-CreationDate",
        "-MediaCreateDate",
        "-TrackCreateDate",

        "-Keys:CreationDate",
        "-QuickTime:CreateDate",
        "-QuickTime:CreationDate",
        "-QuickTime:MediaCreateDate",
        "-QuickTime:TrackCreateDate",

        str(path)
    ]

    try:
        creationflags = (
            subprocess.CREATE_NO_WINDOW
            if os.name == "nt"
            else 0
        )

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            creationflags=creationflags
        )

        if not result.stdout.strip():
            return {}

        data = json.loads(result.stdout)

        if isinstance(data, list) and data:
            return data[0]

    except Exception:
        pass

    return {}


# ----------------------------------------------------------
# 태그 검색
# ----------------------------------------------------------

def find_tag(metadata, names):
    """
    ExifTool -G1 사용 시
    EXIF:DateTimeOriginal
    QuickTime:CreateDate
    Keys:CreationDate
    등의 형태가 될 수 있으므로
    그룹명과 관계없이 실제 태그 이름을 검사한다.
    """

    for wanted in names:

        # 정확한 key 먼저
        if wanted in metadata:
            d = parse_dt(metadata[wanted])

            if d:
                return d, wanted

        # 그룹명 포함 key 검사
        for key, value in metadata.items():

            short = key.split(":")[-1]

            if short.lower() == wanted.lower():
                d = parse_dt(value)

                if d:
                    return d, key

    return None, None


# ----------------------------------------------------------
# 파일명 날짜 추출
# ----------------------------------------------------------

def filename_date(path):
    name = path.stem

    patterns = [

        # IMG_20240115_143022
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
        ),

        # Screenshot_2024-01-15
        re.compile(
            r"(19\d{2}|20\d{2})"
            r"[-_]"
            r"(0[1-9]|1[0-2])"
            r"[-_]"
            r"([0-2]\d|3[01])"
        )
    ]

    for pattern in patterns:
        m = pattern.search(name)

        if not m:
            continue

        try:
            year = int(m.group(1))
            month = int(m.group(2))
            day = int(m.group(3))

            hour = (
                int(m.group(4))
                if m.lastindex >= 4 and m.group(4)
                else 0
            )

            minute = (
                int(m.group(5))
                if m.lastindex >= 5 and m.group(5)
                else 0
            )

            second = (
                int(m.group(6))
                if m.lastindex >= 6 and m.group(6)
                else 0
            )

            return datetime(
                year,
                month,
                day,
                hour,
                minute,
                second
            )

        except Exception:
            pass

    return None


# ----------------------------------------------------------
# Pillow EXIF 보조 판정
# ----------------------------------------------------------

def pillow_exif_date(path):
    try:
        from PIL import Image, ExifTags

        with Image.open(path) as im:

            exif = im.getexif()

            if not exif:
                return None, None

            candidates = []

            # 기본 IFD
            for key, value in exif.items():

                tag = ExifTags.TAGS.get(key, str(key))

                if tag in (
                    "DateTimeOriginal",
                    "DateTimeDigitized",
                    "DateTime"
                ):
                    candidates.append((tag, value))

            # ExifIFD
            try:
                sub = exif.get_ifd(0x8769)

                for key, value in sub.items():

                    tag = ExifTags.TAGS.get(key, str(key))

                    if tag in (
                        "DateTimeOriginal",
                        "DateTimeDigitized",
                        "DateTime"
                    ):
                        candidates.append((tag, value))

            except Exception:
                pass

            priority = {
                "DateTimeOriginal": 0,
                "DateTimeDigitized": 1,
                "DateTime": 2
            }

            candidates.sort(
                key=lambda x: priority.get(x[0], 99)
            )

            for tag, value in candidates:

                dt = parse_dt(value)

                if dt:
                    return dt, tag

    except Exception:
        pass

    return None, None


# ----------------------------------------------------------
# 촬영일 판정
# ----------------------------------------------------------

def determine_capture_date(path):

    ext = path.suffix.lower()

    metadata = read_metadata(path)

    # ------------------------------------------------------
    # 사진
    # ------------------------------------------------------

    if ext in IMAGE_EXT:

        # 가장 신뢰도가 높은 실제 촬영일
        dt, tag = find_tag(
            metadata,
            [
                "DateTimeOriginal",
                "DateTimeDigitized"
            ]
        )

        if dt:
            return (
                dt,
                "메타데이터:" + tag,
                "확정",
                ""
            )

        # HEIC/JPG 등 CreateDate
        dt, tag = find_tag(
            metadata,
            [
                "CreateDate"
            ]
        )

        if dt:
            return (
                dt,
                "메타데이터:" + tag,
                "확정",
                ""
            )

        # 일반 DateTime
        dt, tag = find_tag(
            metadata,
            [
                "DateTime"
            ]
        )

        if dt:
            return (
                dt,
                "메타데이터:" + tag,
                "보조",
                ""
            )

        # Pillow 보조 EXIF
        dt, tag = pillow_exif_date(path)

        if dt:
            return (
                dt,
                "EXIF:" + tag,
                "확정",
                ""
            )

    # ------------------------------------------------------
    # 동영상
    # ------------------------------------------------------

    elif ext in VIDEO_EXT:

        # iPhone MOV/MP4에서 현지 촬영시간을 포함할 가능성이 높은 태그
        dt, tag = find_tag(
            metadata,
            [
                "CreationDate"
            ]
        )

        if dt:
            return (
                dt,
                "영상메타데이터:" + tag,
                "확정",
                ""
            )

        # QuickTime CreateDate
        dt, tag = find_tag(
            metadata,
            [
                "CreateDate"
            ]
        )

        if dt:
            return (
                dt,
                "영상메타데이터:" + tag,
                "확정",
                ""
            )

        # Media / Track
        dt, tag = find_tag(
            metadata,
            [
                "MediaCreateDate",
                "TrackCreateDate"
            ]
        )

        if dt:
            return (
                dt,
                "영상메타데이터:" + tag,
                "보조",
                ""
            )

    # ------------------------------------------------------
    # 파일명 날짜
    # ------------------------------------------------------

    fn_dt = filename_date(path)

    if fn_dt:

        return (
            fn_dt,
            "파일명 날짜",
            "보조",
            "메타데이터 촬영일 없음"
        )

    # ------------------------------------------------------
    # 최후수단 : 파일 수정일
    # ------------------------------------------------------

    dt = datetime.fromtimestamp(
        path.stat().st_mtime
    )

    return (
        dt,
        "파일 수정일(최후수단)",
        "확인필요",
        "실제 촬영일 메타데이터 없음"
    )


# ----------------------------------------------------------
# 메타데이터와 파일명 날짜 충돌 검사
# ----------------------------------------------------------

def check_date_conflict(path, capture_dt, method):
    fn = filename_date(path)

    if not fn:
        return ""

    if method.startswith("파일명"):
        return ""

    # 180일 이상 차이나면 검토 표시
    try:
        diff = abs((capture_dt.date() - fn.date()).days)

        if diff >= 180:
            return (
                f"날짜 충돌: 메타데이터 "
                f"{capture_dt:%Y-%m-%d} / "
                f"파일명 {fn:%Y-%m-%d}"
            )

    except Exception:
        pass

    return ""


# ----------------------------------------------------------
# SHA256
# ----------------------------------------------------------

def sha256(path):
    h = hashlib.sha256()

    with open(path, "rb") as f:

        for block in iter(
            lambda: f.read(4 * 1024 * 1024),
            b""
        ):
            h.update(block)

    return h.hexdigest()


# ----------------------------------------------------------
# 동일 이름 처리
# ----------------------------------------------------------

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


# ----------------------------------------------------------
# GUI
# ----------------------------------------------------------

class App:

    def __init__(self, root):

        self.root = root

        root.title(APP)
        root.geometry("800x570")

        self.src = tk.StringVar()
        self.dst = tk.StringVar()

        self.videos = tk.BooleanVar(value=True)
        self.dups = tk.BooleanVar(value=False)

        self.q = queue.Queue()

        frame = ttk.Frame(
            root,
            padding=14
        )

        frame.pack(
            fill="both",
            expand=True
        )

        ttk.Label(
            frame,
            text="원본 폴더 (읽기만 함)"
        ).grid(
            row=0,
            column=0,
            sticky="w"
        )

        ttk.Entry(
            frame,
            textvariable=self.src,
            width=72
        ).grid(
            row=1,
            column=0,
            sticky="ew",
            padx=(0, 8)
        )

        ttk.Button(
            frame,
            text="찾아보기",
            command=lambda: self.pick(self.src)
        ).grid(
            row=1,
            column=1
        )

        ttk.Label(
            frame,
            text="정리본 저장 폴더"
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(12, 0)
        )

        ttk.Entry(
            frame,
            textvariable=self.dst,
            width=72
        ).grid(
            row=3,
            column=0,
            sticky="ew",
            padx=(0, 8)
        )

        ttk.Button(
            frame,
            text="찾아보기",
            command=lambda: self.pick(self.dst)
        ).grid(
            row=3,
            column=1
        )

        ttk.Checkbutton(
            frame,
            text="동영상도 정리 (MOV/MP4 등)",
            variable=self.videos
        ).grid(
            row=4,
            column=0,
            sticky="w",
            pady=(12, 0)
        )

        ttk.Checkbutton(
            frame,
            text="완전 동일 중복파일도 중복검토 폴더에 복사",
            variable=self.dups
        ).grid(
            row=5,
            column=0,
            sticky="w"
        )

        ttk.Label(
            frame,
            text=(
                "촬영일 우선순위: 사진 EXIF/HEIC 메타데이터 → "
                "영상 QuickTime 메타데이터 → 파일명 → "
                "파일 수정일(확인필요)"
            )
        ).grid(
            row=6,
            column=0,
            columnspan=2,
            sticky="w",
            pady=(10, 4)
        )

        ttk.Label(
            frame,
            text=(
                "※ 원본 파일은 삭제하거나 이동하지 않습니다. "
                "정리본 폴더에 복사만 합니다."
            )
        ).grid(
            row=7,
            column=0,
            columnspan=2,
            sticky="w"
        )

        self.pb = ttk.Progressbar(
            frame,
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
            frame,
            text="준비됨"
        )

        self.status.grid(
            row=9,
            column=0,
            columnspan=2,
            sticky="w"
        )

        self.log = tk.Text(
            frame,
            height=15,
            state="disabled"
        )

        self.log.grid(
            row=10,
            column=0,
            columnspan=2,
            sticky="nsew",
            pady=(8, 8)
        )

        buttons = ttk.Frame(frame)

        buttons.grid(
            row=11,
            column=0,
            columnspan=2,
            sticky="e"
        )

        self.startb = ttk.Button(
            buttons,
            text="정리 시작",
            command=self.start
        )

        self.startb.pack(
            side="left",
            padx=4
        )

        ttk.Button(
            buttons,
            text="종료",
            command=root.destroy
        ).pack(
            side="left"
        )

        frame.columnconfigure(
            0,
            weight=1
        )

        frame.rowconfigure(
            10,
            weight=1
        )

        root.after(
            100,
            self.poll
        )


    def pick(self, var):

        p = filedialog.askdirectory()

        if p:
            var.set(p)


    def write(self, text):

        self.log.configure(
            state="normal"
        )

        self.log.insert(
            "end",
            text + "\n"
        )

        self.log.see("end")

        self.log.configure(
            state="disabled"
        )


    def start(self):

        src = Path(
            self.src.get()
        )

        dst = Path(
            self.dst.get()
        )

        if not src.is_dir():

            return messagebox.showerror(
                APP,
                "원본 폴더를 선택하세요."
            )

        if not self.dst.get():

            return messagebox.showerror(
                APP,
                "정리본 저장 폴더를 선택하세요."
            )

        dst.mkdir(
            parents=True,
            exist_ok=True
        )

        try:

            if (
                same_path(src, dst)
                or
                str(dst.resolve()).lower().startswith(
                    str(src.resolve()).lower()
                    + os.sep
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
            "V2.1 촬영일 검사를 시작합니다..."
        )

        threading.Thread(
            target=self.worker,
            args=(src, dst),
            daemon=True
        ).start()


    def worker(self, src, dst):

        exts = set(IMAGE_EXT)

        if self.videos.get():
            exts |= VIDEO_EXT

        files = [
            p
            for p in src.rglob("*")
            if p.is_file()
            and p.suffix.lower() in exts
        ]

        total = len(files)

        seen = {}
        rows = []

        copied = 0
        duplicate_count = 0
        errors = 0
        confirm_count = 0
        conflict_count = 0

        self.q.put(
            ("max", max(total, 1))
        )

        self.q.put(
            (
                "log",
                f"대상 파일: {total:,}개"
            )
        )

        for i, path in enumerate(
            files,
            1
        ):

            try:

                dt, method, confidence, note = \
                    determine_capture_date(path)

                conflict = check_date_conflict(
                    path,
                    dt,
                    method
                )

                if conflict:

                    conflict_count += 1

                    if note:
                        note += " / " + conflict
                    else:
                        note = conflict

                if confidence == "확인필요":
                    confirm_count += 1

                file_hash = sha256(path)

                duplicate = (
                    file_hash in seen
                )

                if (
                    duplicate
                    and
                    not self.dups.get()
                ):

                    rows.append([
                        path.name,
                        dt.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        method,
                        confidence,
                        str(path),
                        "",
                        "중복-건너뜀",
                        seen[file_hash],
                        note
                    ])

                    duplicate_count += 1

                else:

                    if duplicate:

                        base = (
                            dst
                            / "중복검토"
                            / f"{dt.year:04d}"
                            / f"{dt.month:02d}"
                        )

                    else:

                        base = (
                            dst
                            / f"{dt.year:04d}"
                            / f"{dt.month:02d}"
                        )

                    base.mkdir(
                        parents=True,
                        exist_ok=True
                    )

                    out = unique_dest(
                        base,
                        path.name
                    )

                    shutil.copy2(
                        path,
                        out
                    )

                    if (
                        path.stat().st_size
                        !=
                        out.stat().st_size
                    ):

                        raise IOError(
                            "복사 후 파일 크기 불일치"
                        )

                    rows.append([
                        path.name,
                        dt.strftime(
                            "%Y-%m-%d %H:%M:%S"
                        ),
                        method,
                        confidence,
                        str(path),
                        str(out),
                        (
                            "중복-복사"
                            if duplicate
                            else "정상"
                        ),
                        "",
                        note
                    ])

                    copied += 1

                    if duplicate:
                        duplicate_count += 1

                seen.setdefault(
                    file_hash,
                    str(path)
                )

            except Exception as e:

                errors += 1

                rows.append([
                    path.name,
                    "",
                    "오류",
                    "",
                    str(path),
                    "",
                    "오류",
                    "",
                    str(e)
                ])

            if (
                i % 10 == 0
                or
                i == total
            ):

                self.q.put(
                    (
                        "progress",
                        i,
                        (
                            f"{i:,}/{total:,} 처리 중 — "
                            f"{path.name}"
                        )
                    )
                )

        report = (
            dst
            / "사진정리_결과.csv"
        )

        with open(
            report,
            "w",
            newline="",
            encoding="utf-8-sig"
        ) as f:

            writer = csv.writer(f)

            writer.writerow([
                "파일명",
                "촬영일",
                "날짜판정방식",
                "신뢰도",
                "원본경로",
                "정리경로",
                "중복여부/결과",
                "중복원본",
                "비고"
            ])

            writer.writerows(rows)

        result = (
            f"완료\n\n"
            f"복사: {copied:,}개\n"
            f"중복: {duplicate_count:,}개\n"
            f"확인필요: {confirm_count:,}개\n"
            f"날짜충돌: {conflict_count:,}개\n"
            f"오류: {errors:,}개\n\n"
            f"결과표:\n{report}"
        )

        self.q.put(
            ("done", result)
        )


    def poll(self):

        try:

            while True:

                item = self.q.get_nowait()

                if item[0] == "max":

                    self.pb["maximum"] = item[1]

                elif item[0] == "progress":

                    self.pb["value"] = item[1]

                    self.status.config(
                        text=item[2]
                    )

                elif item[0] == "log":

                    self.write(
                        item[1]
                    )

                elif item[0] == "done":

                    self.write(
                        item[1]
                    )

                    self.status.config(
                        text="완료"
                    )

                    self.startb.config(
                        state="normal"
                    )

                    messagebox.showinfo(
                        APP,
                        item[1]
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
