import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

BASE_DIR = Path(__file__).resolve().parent

def build():
    print("=" * 60)
    print("BAT DAU DONG GOI TIKTOK AUTO TOOL THANH FILE .EXE")
    print("=" * 60)

    dist_dir = BASE_DIR / "dist"
    build_dir = BASE_DIR / "build"

    # Xoa cac thu muc build cu neu co
    if dist_dir.exists():
        try:
            shutil.rmtree(dist_dir)
        except Exception as e:
            print(f"Canh bao khi xoa dist cu: {e}")

    if build_dir.exists():
        try:
            shutil.rmtree(build_dir)
        except Exception as e:
            print(f"Canh bao khi xoa build cu: {e}")

    # Lenh PyInstaller
    # Su dung --onedir de khoi dong tuc thi,
    # tuong thich 100% voi Playwright driver va tranh bi Windows Defender chan temp extraction.
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "TikTok_Auto_Tool",
        "--onedir",
        "--windowed",
        "--noconfirm",
        "--clean",
        "--collect-all", "playwright",
        "--hidden-import", "sqlite3",
        "--hidden-import", "core.account_parser",
        "--hidden-import", "core.browser_manager",
        "--hidden-import", "core.error_codes",
        "--hidden-import", "core.follow_worker",
        "--hidden-import", "core.tiktok_scraper",
        "--hidden-import", "gui.main_window",
        str(BASE_DIR / "main.py")
    ]

    print("Dang chay PyInstaller...")
    print(" ".join(cmd))
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode != 0:
        print("❌ DONG GOI THAT BAI!")
        sys.exit(res.returncode)

    output_folder = dist_dir / "TikTok_Auto_Tool"
    if not output_folder.exists():
        print(f"❌ Khong tim thay thu muc dau ra: {output_folder}")
        sys.exit(1)

    print("\nSao chep cac file huong dan va mau tai khoan vao thu muc phan phoi...")
    files_to_copy = [
        "Huong_Dan_Su_Dung.txt",
        "danh_sach_acc_mau.txt",
        "danh_sach_target_mau.txt",
    ]
    for fn in files_to_copy:
        src = BASE_DIR / fn
        if src.exists():
            dst = output_folder / fn
            shutil.copy2(src, dst)
            print(f" -> Da sao chep: {fn}")

    # Tao file zip de nguoi dung tien gui cho ban be
    zip_path = dist_dir / "TikTok_Auto_Tool_v1.0.zip"
    print(f"\nDang nen toan bo thu muc thanh file zip: {zip_path.name}...")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(output_folder):
            for file in files:
                full_path = Path(root) / file
                rel_path = full_path.relative_to(dist_dir)
                zipf.write(full_path, rel_path)

    print("\n" + "=" * 60)
    print("DONG GOI HOAN TAT THANH CONG!")
    print(f"Thu muc tool: {output_folder}")
    print(f"File chay chinh: {output_folder / 'TikTok_Auto_Tool.exe'}")
    print(f"File nen de gui cho ban be: {zip_path}")
    print("=" * 60)

if __name__ == "__main__":
    build()
