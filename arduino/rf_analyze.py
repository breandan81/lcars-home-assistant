#!/usr/bin/env python3
"""
rf_analyze.py — extract a clean repeating RF code from a raw pulse dump.

Usage:
    python3 rf_analyze.py dump.txt          # from a saved file
    python3 rf_analyze.py                   # paste RFRAW line, then Ctrl-D

Input: one line starting with RFRAW from the sketch's D command, e.g.
    RFRAW firstHigh=1 count=347 pulses=320 9120 560 1680 ...

Output:
    - Detected sync pulse width and frame count
    - Pulse-width clusters (what "short" and "long" look like)
    - The cleaned single-frame sequence as a line you can paste into L command
"""

import sys
import re
from collections import Counter
from statistics import mean, stdev

# ── parse ─────────────────────────────────────────────────────────────────
def parse_dump(text):
    m = re.search(r'firstHigh=(\d)\s+count=\d+\s+pulses=([\d\s]+)', text)
    if not m:
        # fallback: just a list of numbers
        first_high = True
        nums = list(map(int, text.split()))
    else:
        first_high = bool(int(m.group(1)))
        nums = list(map(int, m.group(2).split()))
    return first_high, nums

# ── quantize pulses into clusters ─────────────────────────────────────────
def cluster_widths(pulses, n_clusters=4):
    """Simple 1-D k-means to find pulse width buckets."""
    sorted_p = sorted(set(pulses))
    # seed: evenly spaced across range
    lo, hi = sorted_p[0], sorted_p[-1]
    centers = [lo + (hi - lo) * i / (n_clusters - 1) for i in range(n_clusters)]

    for _ in range(20):
        groups = [[] for _ in range(n_clusters)]
        for p in pulses:
            nearest = min(range(n_clusters), key=lambda i: abs(p - centers[i]))
            groups[nearest].append(p)
        new_centers = [mean(g) if g else centers[i] for i, g in enumerate(groups)]
        if new_centers == centers:
            break
        centers = new_centers

    # remove empty clusters
    clusters = [(int(mean(g)), g) for g in groups if g]
    clusters.sort()
    return clusters

# ── find sync boundaries ──────────────────────────────────────────────────
def find_sync_threshold(pulses):
    """
    The sync/gap pulse is usually the longest by a significant margin.
    We look for a bimodal distribution where the top cluster is ≥3× the
    next-largest cluster — that gap is the frame separator.
    """
    clusters = cluster_widths(pulses)
    if len(clusters) < 2:
        return None

    # Check from largest cluster downward for a big jump
    centers = [c[0] for c in clusters]
    for i in range(len(centers) - 1, 0, -1):
        if centers[i] >= 3 * centers[i - 1]:
            # threshold halfway between the two clusters
            return (centers[i] + centers[i - 1]) // 2

    # Fallback: anything > 2× the median
    med = sorted(pulses)[len(pulses) // 2]
    return med * 2

# ── split into frames ─────────────────────────────────────────────────────
def split_frames(pulses, sync_threshold):
    """Split pulse list at any pulse wider than sync_threshold."""
    frames = []
    current = []
    for p in pulses:
        if p >= sync_threshold:
            if len(current) >= 6:
                frames.append(current)
            current = []
        else:
            current.append(p)
    if len(current) >= 6:
        frames.append(current)
    return frames

# ── find most common frame ────────────────────────────────────────────────
def best_frame(frames, tolerance=0.20):
    """
    Among all captured frames, find the one that matches the most others
    within ±tolerance of each pulse width. Returns (frame, match_count).
    """
    if not frames:
        return None, 0

    def frames_match(a, b):
        if len(a) != len(b):
            return False
        return all(abs(x - y) <= tolerance * max(x, y) for x, y in zip(a, b))

    best = None
    best_score = 0
    for i, f in enumerate(frames):
        score = sum(1 for j, g in enumerate(frames) if i != j and frames_match(f, g))
        if score > best_score:
            best_score = score
            best = f
    return best, best_score

# ── quantize a frame to rounded values ───────────────────────────────────
def quantize_frame(frame, all_pulses):
    clusters = cluster_widths(all_pulses)
    centers = [c[0] for c in clusters]

    def nearest(v):
        return min(centers, key=lambda c: abs(v - c))

    return [nearest(p) for p in frame]

# ── main ──────────────────────────────────────────────────────────────────
def main():
    if len(sys.argv) > 1:
        text = open(sys.argv[1]).read()
    else:
        print("Paste the RFRAW line from the sketch (then Ctrl-D):")
        text = sys.stdin.read()

    first_high, pulses = parse_dump(text)

    print(f"\nTotal pulses captured: {len(pulses)}")
    print(f"First pulse polarity: {'HIGH' if first_high else 'LOW'}")
    print(f"Duration range: {min(pulses)}µs – {max(pulses)}µs")

    # Cluster analysis
    clusters = cluster_widths(pulses)
    print(f"\nPulse width clusters ({len(clusters)} found):")
    for center, group in clusters:
        print(f"  ~{center:5d}µs  ×{len(group):4d}  "
              f"(range {min(group)}–{max(group)}µs)")

    # Find sync threshold
    sync_thresh = find_sync_threshold(pulses)
    if sync_thresh:
        sync_count = sum(1 for p in pulses if p >= sync_thresh)
        print(f"\nSync threshold: >{sync_thresh}µs  "
              f"({sync_count} sync pulses found)")
    else:
        print("\nNo clear sync pulse found — all pulses similar width")
        print("Trying with 2× median as threshold...")
        sync_thresh = sorted(pulses)[len(pulses) // 2] * 2

    # Split and analyse frames
    frames = split_frames(pulses, sync_thresh)
    print(f"Frames detected: {len(frames)}")
    if frames:
        lengths = Counter(len(f) for f in frames)
        print(f"Frame lengths: {dict(lengths)}")

    if len(frames) < 2:
        print("\nToo few frames — try capturing with button held longer,")
        print("or the sync threshold may be wrong. Check the cluster output above.")
        # Still output what we have
        if frames:
            frame = frames[0]
        else:
            print("No usable frames found.")
            return
        matches = 0
    else:
        frame, matches = best_frame(frames)
        print(f"\nBest frame: {len(frame)} pulses, matched {matches}/{len(frames)-1} other frames")

    if not frame:
        print("Could not extract a consistent frame.")
        return

    # Quantize to clean values
    qframe = quantize_frame(frame, pulses)

    print("\n── Cleaned frame ──────────────────────────────────────")
    pol = 'H' if first_high else 'L'
    output = pol + ' ' + ' '.join(str(p) for p in qframe)
    print(output)
    print("\n── Paste the line above into the sketch's L command ──")

    # Also show human-readable bit pattern if 2 distinct pulse widths
    data_pulses = [p for p in pulses if p < sync_thresh]
    data_clusters = cluster_widths(data_pulses, n_clusters=2)
    if len(data_clusters) == 2:
        short_c, long_c = data_clusters[0][0], data_clusters[1][0]
        print(f"\nBit encoding (short={short_c}µs, long={long_c}µs):")
        bits = []
        for i in range(0, len(qframe) - 1, 2):
            mark, space = qframe[i], qframe[i+1]
            if abs(space - short_c) < abs(space - long_c):
                bits.append('0')
            else:
                bits.append('1')
        if bits:
            bitstr = ''.join(bits)
            print(f"  {bitstr}")
            print(f"  0x{int(bitstr, 2):0{(len(bitstr)+3)//4}X}  ({len(bitstr)} bits)")

if __name__ == '__main__':
    main()
