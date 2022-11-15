from pathlib import Path
import subprocess


def main():
    tmp = Path('/home/tmp')
    for folder in tmp.iterdir():
        subprocess.run(['sudo', 'rm', '-r', str(folder)])
main()
