#!/usr/bin/env python3
"""
rf_analyze.py — extract a clean repeating RF frame from a raw pulse dump.

Usage:
    python3 rf_analyze.py                   # paste RFRAW line, then Ctrl-D
    python3 rf_analyze.py dump.txt          # from a saved file
    python3 rf_analyze.py --sync 6000       # manually set sync threshold (µs)

Input: one line starting with RFRAW from the sketch's D command, e.g.
    RFRAW firstHigh=1 count=347 pulses=320 9120 560 1680 ...

Output:
    - Pulse width clusters
    - Detected sync threshold and frame count
    - One clean raw frame (unquantized) ready to paste into the L command
"""

import sys
import re
import argparse
from collections import Counter
from statistics import mean

# ── parse ─────────────────────────────────────────────────────────────────
def parse_dump(text):
    m = re.search(r'firstHigh=(\d)\s+count=\d+\s+pulses=([\d\s,]+)', text)
    if not m:
        first_high = True
        nums = list(map(int, re.split(r'[\s,]+', text.strip())))
    else:
        first_high = bool(int(m.group(1)))
        nums = list(map(int, re.split(r'[\s,]+', m.group(2).strip())))
    return first_high, [n for n in nums if n > 0]

# ── cluster pulse widths ──────────────────────────────────────────────────
def cluster_widths(pulses, n_clusters=4):
    if len(pulses) < n_clusters:
        return [(int(mean(pulses)), pulses)]
    sorted_p = sorted(set(pulses))
    lo, hi = sorted_p[0], sorted_p[-1]
    centers = [lo + (hi - lo) * i / (n_clusters - 1) for i in range(n_clusters)]
    for _ in range(30):
        groups = [[] for _ in range(n_clusters)]
        for p in pulses:
            nearest = min(range(n_clusters), key=lambda i: abs(p - centers[i]))
            groups[nearest].append(p)
        new_centers = [mean(g) if g else centers[i] for i, g in enumerate(groups)]
        if new_centers == centers:
            break
        centers = new_centers
    clusters = [(int(mean(g)), g) for g in groups if g]
    clusters.sort()
    return clusters

# ── sync threshold detection ──────────────────────────────────────────────
def find_sync_threshold(pulses, manual=None):
    """
    Return the threshold above which a pulse is a sync/gap rather than data.

    Strategy (without manual override):
      1. Cluster the pulses into up to 4 groups.
      2. Data pulses appear frequently (>3% of all pulses).
         Sync pulses appear rarely.
      3. Find the highest-frequency cluster, then set threshold just above
         the highest cluster that still exceeds the 3% frequency cutoff.
      4. Fallback: first cluster that is ≥3× the previous cluster center.
    """
    if manual:
        return manual

    total = len(pulses)
    clusters = cluster_widths(pulses)
    centers = [c for c, _ in clusters]
    counts  = [len(g) for _, g in clusters]

    # Frequency-based: clusters with >3% of pulses are data
    data_threshold = 0.03 * total
    data_clusters = [(c, n) for c, n in zip(centers, counts) if n >= data_threshold]

    if data_clusters:
        highest_data_center = max(c for c, _ in data_clusters)
        # Sync threshold = midpoint between highest data cluster and next one up
        above = [c for c in centers if c > highest_data_center]
        if above:
            return (highest_data_center + min(above)) // 2

    # Fallback: 3× jump rule (top-down)
    for i in range(len(centers) - 1, 0, -1):
        if centers[i] >= 3 * centers[i - 1]:
            return (centers[i] + centers[i - 1]) // 2

    # Last resort: 2× median
    return sorted(pulses)[len(pulses) // 2] * 2

# ── split into frames ─────────────────────────────────────────────────────
def split_frames(pulses, sync_threshold):
    """
    Split at sync pulses. Returns list of (sync_pulse, data_pulses) tuples.
    sync_pulse is the gap that preceded this frame (0 for the first).
    """
    frames = []
    current = []
    last_sync = 0
    for p in pulses:
        if p >= sync_threshold:
            if len(current) >= 6:
                frames.append((last_sync, current))
            current = []
            last_sync = p
        else:
            current.append(p)
    if len(current) >= 6:
        frames.append((last_sync, current))
    return frames

# ── find best matching frame ──────────────────────────────────────────────
def best_frame(frame_tuples, tolerance=0.20, len_tolerance=0.15):
    """Find the frame that matches the most others by pulse timing."""
    if not frame_tuples:
        return None, 0, 0

    def len_compat(a, b):
        longer = max(len(a), len(b))
        return abs(len(a) - len(b)) <= len_tolerance * longer

    def frames_match(a, b):
        if not len_compat(a, b):
            return False
        n = min(len(a), len(b))
        return all(abs(x - y) <= tolerance * max(x, y) for x, y in zip(a[:n], b[:n]))

    data_arrays = [d for _, d in frame_tuples]
    best_d, best_s, best_score = None, 0, -1
    for i, (s, d) in enumerate(frame_tuples):
        score = sum(1 for j, g in enumerate(data_arrays) if i != j and frames_match(d, g))
        if score > best_score:
            best_score = score
            best_d = d
            best_s = s

    # Fallback: frame closest to median length
    if best_d is None or best_score == 0:
        med = sorted(len(d) for _, d in frame_tuples)[len(frame_tuples) // 2]
        best_s, best_d = min(frame_tuples, key=lambda t: abs(len(t[1]) - med))

    return best_s, best_d, best_score

# ── main ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='Extract RF frame from raw pulse dump')
    parser.add_argument('file', nargs='?', help='File containing RFRAW line')
    parser.add_argument('--sync', type=int, default=None,
                        help='Manual sync threshold in µs (overrides auto-detection)')
    args = parser.parse_args()

    if args.file:
        text = open(args.file).read()
    else:
        print("Paste the RFRAW line from the sketch (then Ctrl-D):")
        text = sys.stdin.read()

    first_high, pulses = parse_dump(text)
    if not pulses:
        print("No pulses found in input.")
        return

    print(f"\nTotal pulses captured: {len(pulses)}")
    print(f"First pulse polarity: {'HIGH' if first_high else 'LOW'}")
    print(f"Duration range: {min(pulses)}µs – {max(pulses)}µs")

    clusters = cluster_widths(pulses)
    print(f"\nPulse width clusters ({len(clusters)} found):")
    for center, group in clusters:
        pct = 100 * len(group) / len(pulses)
        print(f"  ~{center:6d}µs  ×{len(group):4d}  ({pct:4.1f}%)  "
              f"range {min(group)}–{max(group)}µs"
              + ("  ← likely data" if len(group) / len(pulses) > 0.03 else "  ← likely sync/gap"))

    sync_thresh = find_sync_threshold(pulses, args.sync)
    sync_count = sum(1 for p in pulses if p >= sync_thresh)
    print(f"\nSync threshold: >{sync_thresh}µs  ({sync_count} sync pulses)")
    if args.sync:
        print("  (manually set)")
    else:
        print("  (auto-detected — use --sync N to override)")

    frame_tuples = split_frames(pulses, sync_thresh)
    print(f"Frames detected: {len(frame_tuples)}")
    if frame_tuples:
        lengths = Counter(len(d) for _, d in frame_tuples)
        print(f"Frame lengths: {dict(lengths)}")

    # Filter noise frames
    if frame_tuples:
        med = sorted(len(d) for _, d in frame_tuples)[len(frame_tuples) // 2]
        frame_tuples = [(s, d) for s, d in frame_tuples
                        if len(d) >= 6 and len(d) <= med * 3]
        print(f"After noise filter: {len(frame_tuples)} frame(s)")

    if not frame_tuples:
        print("\nNo usable frames — try adjusting --sync threshold.")
        return

    sync_val, frame, matches = best_frame(frame_tuples)
    print(f"\nSelected frame: {len(frame)} pulses"
          + (f", matched {matches}/{len(frame_tuples)-1} others" if len(frame_tuples) > 1 else ""))

    # Output raw (unquantized) frame with sync pulse prepended
    if sync_val > 0:
        full = [sync_val] + frame
        print(f"Sync pulse prepended: {sync_val}µs")
    else:
        full = frame

    pol = 'H' if first_high else 'L'
    output = pol + ' ' + ' '.join(str(p) for p in full)

    print("\n── Raw frame (sync + data, unquantized) ───────────────")
    print(output)
    print("\n── Paste the line above into the sketch's L command ──")
    print(f"\nTotal output pulses: {len(full)}")

if __name__ == '__main__':
    main()
