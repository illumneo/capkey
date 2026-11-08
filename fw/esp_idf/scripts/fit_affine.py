#!/usr/bin/env python3
import argparse
import math
import re
from typing import List, Sequence, Tuple


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Fit an affine transform from measured contacts to a 4x4 grid. "
                                "Every file must contain one complete declared target sequence.")
    p.add_argument("logfiles", nargs="+", help="Log files to parse (e.g., logs/run5.log logs/run6.log)")
    p.add_argument("--z-on", type=float, default=2.0, help="Z threshold to start a tap (default: 2.0)")
    p.add_argument("--z-off", type=float, default=1.0, help="Z threshold to end a tap (default: 1.0)")
    p.add_argument("--min-samples", type=int, default=3, help="Minimum samples per tap (default: 3)")
    p.add_argument("--expected", type=str, default=None,
                   help="Comma-separated target order (x:y pairs, e.g., 0:0,1:0,...; default: row-major integer centres 0..3)")
    p.add_argument("--taps-per-target", type=int, default=1,
                   help="Consecutive contacts at each target, in every input file (default: 1)")
    args = p.parse_args(argv)
    if not math.isfinite(args.z_on) or not math.isfinite(args.z_off) or not 0 <= args.z_off < args.z_on:
        p.error("thresholds must be finite and satisfy 0 <= z-off < z-on")
    if args.min_samples < 1 or args.taps_per_target < 1:
        p.error("min-samples and taps-per-target must be positive integers")
    return args


def expected_targets(spec=None, taps_per_target=1) -> List[Tuple[float, float]]:
    """Expand declared intent; repetition means consecutive taps at each target."""
    if type(taps_per_target) is not int or taps_per_target < 1:
        raise ValueError("taps-per-target must be a positive integer")
    if spec is None:
        targets = [(float(i % 4), float(i // 4)) for i in range(16)]
    else:
        targets = []
        for index, pair in enumerate(spec.split(","), 1):
            values = pair.split(":")
            if len(values) != 2:
                raise ValueError(f"Expected target {index} must be an x:y pair: {pair!r}")
            try:
                target = tuple(float(value) for value in values)
            except ValueError as exc:
                raise ValueError(f"Expected target {index} has invalid coordinates: {pair!r}") from exc
            if not all(math.isfinite(value) for value in target):
                raise ValueError(f"Expected target {index} must have finite coordinates")
            targets.append(target)
    return [target for target in targets for _ in range(taps_per_target)]


def load_centroids(path: str) -> List[Tuple[float, float, float]]:
    pat = re.compile(r"centroid \(x,y,z\)x1e3 = \(([+-]?[0-9]+),\s*([+-]?[0-9]+),\s*([+-]?[0-9]+)\)")
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for number, line in enumerate(f, 1):
            m = pat.search(line)
            if not m:
                if "centroid (x,y,z)" in line:
                    raise ValueError(f"{path}:{number}: malformed centroid record")
                continue
            try:
                sample = tuple(int(value) / 1000.0 for value in m.groups())
            except (ValueError, OverflowError) as exc:
                raise ValueError(f"{path}:{number}: invalid centroid value") from exc
            out.append(sample)
    return out


def detect_taps(samples: Sequence[Tuple[float, float, float]],
                z_on: float, z_off: float, min_samples: int) -> List[List[Tuple[float, float, float]]]:
    if not math.isfinite(z_on) or not math.isfinite(z_off) or not 0 <= z_off < z_on:
        raise ValueError("thresholds must be finite and satisfy 0 <= z-off < z-on")
    if type(min_samples) is not int or min_samples < 1:
        raise ValueError("min-samples must be a positive integer")
    taps: List[List[Tuple[float, float, float]]] = []
    current: List[Tuple[float, float, float]] = []
    in_touch = False
    for s in samples:
        x, y, z = s
        if not all(math.isfinite(value) for value in s):
            raise ValueError("Centroid samples must be finite")
        if not in_touch and z >= z_on:
            in_touch = True
            current = [s]
        elif in_touch and z < z_off:
            if len(current) < min_samples:
                raise ValueError(f"Contact {len(taps) + 1} has only {len(current)} samples; "
                                 f"minimum is {min_samples}. Refusing to silently shift subsequent labels")
            taps.append(current)
            in_touch = False
            current = []
        elif in_touch:
            current.append(s)
    if in_touch:
        raise ValueError(f"Contact {len(taps) + 1} is unterminated at end of file; a release sample is required")
    return taps


def collect_correspondences(logfiles, targets, z_on, z_off, min_samples):
    """Each file must independently contain one complete declared sequence."""
    sources, destinations, origins = [], [], []
    for path in logfiles:
        try:
            taps = detect_taps(load_centroids(path), z_on, z_off, min_samples)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
        if len(taps) != len(targets):
            raise ValueError(f"{path}: found {len(taps)} complete contacts, expected exactly {len(targets)}. "
                             "No contacts were truncated or assigned partial labels; check --taps-per-target and the declared order")
        sources.extend((sum(p[0] for p in tap) / len(tap), sum(p[1] for p in tap) / len(tap)) for tap in taps)
        destinations.extend(targets)
        origins.extend((str(path), number) for number in range(1, len(taps) + 1))
    return sources, destinations, origins


def affine_fit(src: Sequence[Tuple[float, float]],
               dst: Sequence[Tuple[float, float]]):
    if len(src) != len(dst) or len(src) < 3:
        raise ValueError("Affine fitting requires at least three equally sized source/target pairs")
    # Solve for x' = a x + b y + t, y' = c x + d y + u via least squares (normal equations 3x3 for each)
    def solve(targets):
        A = [[0.0] * 3 for _ in range(3)]
        b = [0.0] * 3
        for (x, y), T in zip(src, targets):
            A[0][0] += x * x
            A[0][1] += x * y
            A[0][2] += x
            A[1][0] += y * x
            A[1][1] += y * y
            A[1][2] += y
            A[2][0] += x
            A[2][1] += y
            A[2][2] += 1
            b[0] += x * T
            b[1] += y * T
            b[2] += T
        # small ridge to avoid singular matrices when taps collapse
        ridge = 1e-3
        for i in range(3):
            A[i][i] += ridge

        # Gaussian elimination 3x3
        M = [row[:] for row in A]
        rhs = b[:]
        for i in range(3):
            piv = max(range(i, 3), key=lambda r: abs(M[r][i]))
            if abs(M[piv][i]) < 1e-9:
                return None
            if piv != i:
                M[i], M[piv] = M[piv], M[i]
                rhs[i], rhs[piv] = rhs[piv], rhs[i]
            pivv = M[i][i]
            for j in range(i, 3):
                M[i][j] /= pivv
            rhs[i] /= pivv
            for r in range(3):
                if r == i:
                    continue
                factor = M[r][i]
                for j in range(i, 3):
                    M[r][j] -= factor * M[i][j]
                rhs[r] -= factor * rhs[i]
        return rhs  # [a, b, t]

    sx = solve([p[0] for p in dst])
    sy = solve([p[1] for p in dst])
    return sx, sy


def main(argv=None):
    args = parse_args(argv)
    try:
        declared = expected_targets(args.expected, args.taps_per_target)
        src_means, dst, origins = collect_correspondences(
            args.logfiles, declared, args.z_on, args.z_off, args.min_samples)
        sx, sy = affine_fit(src_means, dst)
    except (ValueError, OSError) as exc:
        raise SystemExit(f"Calibration input rejected: {exc}") from exc

    if sx is None or sy is None or not all(math.isfinite(value) for value in (*sx, *sy)):
        raise SystemExit("Affine fit failed: coefficients are unavailable or nonfinite")

    print("Labels assume the declared contact order in each file; matching counts alone do not verify intent.")
    print("Affine parameters:")
    print(f"x' = {sx[0]:.6f} * x + {sx[1]:.6f} * y + {sx[2]:.6f}")
    print(f"y' = {sy[0]:.6f} * x + {sy[1]:.6f} * y + {sy[2]:.6f}")
    print("\nMapped taps vs expected:")
    for i, ((mx, my), (ex, ey), (path, contact)) in enumerate(zip(src_means, dst, origins), 1):
        X = sx[0] * mx + sx[1] * my + sx[2]
        Y = sy[0] * mx + sy[1] * my + sy[2]
        print(f"{i:2d} [{path} contact {contact}]: got=({mx:.3f},{my:.3f}) -> map=({X:.3f},{Y:.3f}) exp=({ex:.3f},{ey:.3f}) "
              f"err=({X-ex:+.3f},{Y-ey:+.3f})")


if __name__ == "__main__":
    main()
