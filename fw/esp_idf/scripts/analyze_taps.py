#!/usr/bin/env python3
import argparse
import math
import re
import sys
from typing import List, Sequence, Tuple


DEFAULT_LABELS = [
    "A", "N", "I", "",
    "H", "O", "R", "",
    "T", "E", "S", "",
    "", "", "", "",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract tap centroids from a touch log and summarize per tap.")
    parser.add_argument("logfile", help="Path to log file (e.g., logs/run6.log)")
    parser.add_argument("--z-on", type=float, default=1.3,
                        help="Z threshold to start a tap (default: 1.3)")
    parser.add_argument("--z-off", type=float, default=0.9,
                        help="Z threshold to end a tap (default: 0.9)")
    parser.add_argument("--min-samples", type=int, default=3,
                        help="Minimum samples required to record a tap (default: 3)")
    parser.add_argument("--labels", type=str, default=None,
                        help="Comma-separated 16 labels in tap order; blanks allowed.")
    return parser.parse_args()


def load_centroids(path: str) -> List[Tuple[float, float, float]]:
    pattern = re.compile(r"centroid \(x,y,z\)x1e3 = \(([-0-9]+), ([-0-9]+), ([-0-9]+)\)")
    centroids: List[Tuple[float, float, float]] = []
    with open(path, "r", errors="ignore") as f:
        for line in f:
            m = pattern.search(line)
            if not m:
                continue
            x = int(m.group(1)) / 1000.0
            y = int(m.group(2)) / 1000.0
            z = int(m.group(3)) / 1000.0
            centroids.append((x, y, z))
    return centroids


def detect_taps(samples: Sequence[Tuple[float, float, float]],
                z_on: float,
                z_off: float,
                min_samples: int) -> List[List[Tuple[float, float, float]]]:
    taps: List[List[Tuple[float, float, float]]] = []
    current: List[Tuple[float, float, float]] = []
    in_touch = False

    for s in samples:
        x, y, z = s
        if not in_touch and z >= z_on:
            in_touch = True
            current = [s]
        elif in_touch and z < z_off:
            if len(current) >= min_samples:
                taps.append(current)
            in_touch = False
            current = []
        elif in_touch:
            current.append(s)

    # Handle trailing touch
    if in_touch and len(current) >= min_samples:
        taps.append(current)
    return taps


def stats(tap: Sequence[Tuple[float, float, float]]) -> Tuple[float, float, float,
                                                             float, float,
                                                             float, float,
                                                             float, float]:
    xs = [p[0] for p in tap]
    ys = [p[1] for p in tap]
    zs = [p[2] for p in tap]
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    mean_z = sum(zs) / len(zs)
    std_x = math.sqrt(sum((v - mean_x) ** 2 for v in xs) / len(xs))
    std_y = math.sqrt(sum((v - mean_y) ** 2 for v in ys) / len(ys))
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return mean_x, mean_y, mean_z, std_x, std_y, min_x, max_x, min_y, max_y


def main() -> None:
    args = parse_args()

    labels = DEFAULT_LABELS
    if args.labels:
        labels = [lbl.strip() for lbl in args.labels.split(",")]
        if len(labels) != 16:
            sys.stderr.write("Expected 16 labels when using --labels\\n")
            sys.exit(1)

    centroids = load_centroids(args.logfile)
    if not centroids:
        sys.stderr.write("No centroids found in log\\n")
        sys.exit(1)

    taps = detect_taps(centroids, args.z_on, args.z_off, args.min_samples)

    print(f"Total samples: {len(centroids)}")
    print(f"Detected taps: {len(taps)} (expected {len(labels)})")
    print("idx label samples   mean_x  mean_y  mean_z   std_x  std_y   min_x->max_x   min_y->max_y")
    print("-" * 90)

    for idx, tap in enumerate(taps):
        m_x, m_y, m_z, s_x, s_y, min_x, max_x, min_y, max_y = stats(tap)
        label = labels[idx] if idx < len(labels) else ""
        label_disp = label if label else "(blank)"
        print(f"{idx+1:>3} {label_disp:<7} {len(tap):>7} "
              f"{m_x:6.3f} {m_y:6.3f} {m_z:6.3f} "
              f"{s_x:6.3f} {s_y:6.3f} "
              f"{min_x:6.3f}->{max_x:6.3f} "
              f"{min_y:6.3f}->{max_y:6.3f}")

    if len(taps) != len(labels):
        print("\\nNote: tap count differs from provided labels; verify capture order.")


if __name__ == "__main__":
    main()
