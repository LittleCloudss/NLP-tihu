import argparse
from pathlib import Path
from leg_diagnosis import calibrate
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('output',type=Path)
    raise SystemExit(0 if calibrate(p.parse_args().output) else 1)
