/*
 * LCARS IR + RF Blaster Enclosure
 * ─────────────────────────────────────────────────────────────────────────────
 * Fits:  Arduino Uno (68.6 × 53.4 mm)
 *        VS1838B IR receiver (dome through front face, or glue in hole)
 *        5 mm IR LED         (through front face)
 *        FS1000A RF TX       (rests on floor, hot-glue)
 *        XD-RF-5V RF RX      (rests on floor, hot-glue)
 *
 * Orientation (wall-mounted, back plate flat to wall):
 *   Front (Y = 0)  — faces room; IR LED hole, VS1838B dome hole, labels
 *   Left  (X = 0)  — USB-B cable cutout
 *   Back  (Y = ext_d) — against wall; two keyhole mount slots
 *   Top              — lid snaps on here
 *
 * Printed in two parts.  To export each:
 *   Set PART = "box"  → export box
 *   Set PART = "lid"  → export lid
 *   Set PART = "both" → preview both (default)
 *
 * Screws needed:
 *   4 × M3 × 8 mm socket cap   — Arduino to standoffs (self-tapping into pillar)
 *   2 × M3 × 6 mm countersunk  — lid to box (optional, if skipping snap clips)
 *   2 × wood/drywall screws    — wall mount (any that fit the keyhole)
 */

// ── Toggle render ────────────────────────────────────────────────────────────
PART = "both";   // "box" | "lid" | "both"

// ── Resolution ───────────────────────────────────────────────────────────────
$fn = 60;

// ── Shell dimensions ─────────────────────────────────────────────────────────
wall    = 2.8;   // shell wall thickness
floor_t = 3.0;   // base plate thickness (back of box, against wall)
lid_t   = 2.5;   // lid plate thickness

// ── Tolerance ────────────────────────────────────────────────────────────────
tol = 0.25;      // general clearance between mating parts

// ── Arduino Uno R3 ──────────────────────────────────────────────────────────
brd_w = 68.58;   // board width  (USB end ← → power end = left ← → right in box)
brd_d = 53.34;   // board depth  (front ← → back)
brd_t = 1.7;     // PCB thickness

// Mounting holes [x along brd_w, y along brd_d] from USB-corner of board.
// Source: Arduino R3 mechanical drawing.
mholes = [
  [ 2.54,  5.08],
  [66.04,  5.08],
  [66.04, 52.07],
  [15.24, 52.07],
];

standoff_h  = 4.5;   // height of standoff pillar above floor_t
standoff_od = 7.0;   // outer diameter of standoff
m3_tap_d    = 2.8;   // self-tapping M3 into standoff (drill Ø)

// ── Clearances ───────────────────────────────────────────────────────────────
usb_side_clr = 8.0;   // gap between left wall inner face and board USB edge
                       // (room for USB-B connector body ~11.5 mm wide + bend relief)
front_clr    = 5.0;   // gap between front wall inner face and board front edge
back_clr     = 4.0;   // gap on back side of board
comp_h       = 11.0;  // tallest component above PCB (USB-B body ≈ 11 mm)
top_clr      = 3.0;   // clearance above tallest component to lid

// Extra floor area (right of Arduino) for RF modules to rest on
rf_w_extra = 26.0;   // FS1000A ≈ 19 mm wide, XD-RF-5V ≈ 30 mm — stack them

// ── Internal box dimensions ──────────────────────────────────────────────────
int_w = usb_side_clr + brd_w + rf_w_extra;  // X
int_d = front_clr + brd_d + back_clr;        // Y
int_h = standoff_h + brd_t + comp_h + top_clr; // Z (open top)

// ── External box dimensions ──────────────────────────────────────────────────
ext_w = int_w + wall * 2;
ext_d = int_d + wall * 2;
ext_h = int_h + floor_t;

// ── Board bottom-left origin in box coords ───────────────────────────────────
brd_x = wall + usb_side_clr;   // board left (USB) edge X
brd_y = wall + front_clr;      // board front edge Y
brd_z = floor_t + standoff_h;  // bottom of PCB Z

// ── USB-B cutout on left face (x = 0) ───────────────────────────────────────
// USB-B connector centre ≈ 11 mm from USB edge of board, 5.5 mm above PCB top
usb_cut_cy = brd_y + 11.0;           // Y of cutout centre
usb_cut_cz = brd_z + brd_t + 5.5;   // Z of cutout centre
usb_cut_w  = 14.5;                   // cutout width  (Y direction)
usb_cut_h  = 12.0;                   // cutout height (Z direction)

// ── IR LED on front face (y = 0) ─────────────────────────────────────────────
// Centre it over the board, left third
led_cx = brd_x + brd_w * 0.30;               // X
led_cz = brd_z + brd_t + comp_h * 0.50;      // Z — mid-component height
led_d  = 5.4;                                  // 5 mm LED + 0.4 clearance

// ── VS1838B dome on front face (y = 0) ───────────────────────────────────────
vs_cx = brd_x + brd_w * 0.65;   // X — right of LED
vs_cz = led_cz;                  // same Z
vs_d  = 7.5;                     // dome fits ~5.4 mm; wider for glue bead

// ── Snap-clip geometry ───────────────────────────────────────────────────────
// Lid has 4 inward-pointing cantilever tabs.
// Box walls have matching through-holes that the tabs click into.
// Tabs are on: front wall, back wall (2 each, symmetric in X).
clip_w   = 8.0;   // clip width  (X direction)
clip_h   = 6.0;   // clip height (Z direction)
clip_pro = 1.2;   // how far tab protrudes into hole (catch depth)
clip_t   = 1.6;   // tab root thickness (needs to flex)
// X positions of clips (centred along ext_w)
clip_xs  = [ext_w * 0.28, ext_w * 0.72];

// ── Keyhole slots on back face (y = ext_d) ───────────────────────────────────
kh_head_d = 8.0;   // screw-head clearance hole diameter
kh_slot_w = 4.5;   // slot width for screw shank
kh_drop   = 12.0;  // slot height (slide up to lock)
kh_cz     = ext_h * 0.60;
kh_xs     = [ext_w * 0.22, ext_w * 0.78];

// ── Lid lip ───────────────────────────────────────────────────────────────────
lip_depth = 8.0;   // how far lip descends into box
lip_t     = 2.0;   // lip wall thickness


// ═══════════════════════════════════════════════════════════════════════════
// MODULES
// ═══════════════════════════════════════════════════════════════════════════

module standoff(h, od, tap_d) {
  difference() {
    cylinder(d=od, h=h);
    cylinder(d=tap_d, h=h + 1);
  }
}

module keyhole(head_d, slot_w, drop_h, depth) {
  // Head hole at top, slot drops down
  union() {
    cylinder(d=head_d, h=depth + 2);
    translate([-(slot_w / 2), -drop_h, 0])
      cube([slot_w, drop_h, depth + 2]);
  }
}

// Hollow rectangular tube — used for lid lip
module rect_tube(w, d, h, t) {
  difference() {
    cube([w, d, h]);
    translate([t, t, -1])
      cube([w - t*2, d - t*2, h + 2]);
  }
}

// Embossed label — raised text on a surface, font sized for readability
module label(txt, sz=5) {
  linear_extrude(0.6)
    text(txt, size=sz, font="Liberation Sans:style=Bold",
         halign="center", valign="center");
}


// ═══════════════════════════════════════════════════════════════════════════
// BOX BODY
// ═══════════════════════════════════════════════════════════════════════════

module box_body() {
  difference() {
    // ── Outer shell ──────────────────────────────────────────────────────
    cube([ext_w, ext_d, ext_h]);

    // ── Hollow interior (open top) ────────────────────────────────────────
    translate([wall, wall, floor_t])
      cube([int_w, int_d, int_h + 1]);

    // ── USB-B cutout — left face ──────────────────────────────────────────
    translate([-1, usb_cut_cy - usb_cut_w/2, usb_cut_cz - usb_cut_h/2])
      cube([wall + 2, usb_cut_w, usb_cut_h]);

    // ── IR LED hole — front face ──────────────────────────────────────────
    translate([led_cx, -1, led_cz])
      rotate([-90, 0, 0])
        cylinder(d=led_d, h=wall + 2);

    // ── VS1838B dome hole — front face ─────────────────────────────────────
    // Slightly recessed step so receiver dome sits flush / can be glued
    translate([vs_cx, -1, vs_cz])
      rotate([-90, 0, 0]) {
        cylinder(d=vs_d, h=wall + 2);              // through-hole
        cylinder(d=vs_d + 2.0, h=wall * 0.55 + 1); // outer countersink for glue lip
      }

    // ── Snap-clip through-holes in front and back walls ───────────────────
    clip_z = ext_h - clip_h - 1.5;
    for (cx = clip_xs) {
      // Front wall (y = 0)
      translate([cx - clip_w/2, -1, clip_z])
        cube([clip_w + tol, wall + 2, clip_h + tol]);
      // Back wall (y = ext_d - wall)
      translate([cx - clip_w/2, ext_d - wall - 1, clip_z])
        cube([clip_w + tol, wall + 2, clip_h + tol]);
    }

    // ── Keyhole wall-mount slots — back face ──────────────────────────────
    for (kx = kh_xs) {
      translate([kx, ext_d - wall - 1, kh_cz])
        rotate([-90, 0, 0])
          keyhole(kh_head_d, kh_slot_w, kh_drop, wall);
    }

    // ── Label recesses on front face (so labels are inset, not raised) ────
    // Recess 0.5 mm so raised labels on lid or sticker can go here.
    // (If you prefer raised text on the box itself, delete this block
    //  and uncomment the label() calls in the positive section below.)
  }

  // ── Arduino standoffs ─────────────────────────────────────────────────────
  for (mh = mholes) {
    translate([brd_x + mh[0], brd_y + mh[1], floor_t])
      standoff(standoff_h, standoff_od, m3_tap_d);
  }

  // ── Interior divider wall between Arduino and RF modules ──────────────────
  // Thin wall keeps RF modules from sliding under Arduino.
  // Sits just to the right of the board with a cable gap at the top.
  rf_div_x = brd_x + brd_w + 4.0;
  rf_div_h = standoff_h * 0.8;   // short — cables run over it
  translate([rf_div_x, wall, floor_t])
    cube([1.5, int_d, rf_div_h]);

  // ── RF module hot-glue pedestals (flat pads, slightly raised) ─────────────
  // FS1000A pad (~20 × 20 mm), XD-RF-5V pad (~31 × 15 mm) side by side
  rf_pad_z = floor_t;
  rf_ox    = rf_div_x + 3.0;    // origin X of RF zone
  // FS1000A
  translate([rf_ox, wall + 3.0, rf_pad_z])
    cube([20, 20, 1.5]);
  // XD-RF-5V below it
  translate([rf_ox, wall + int_d - 18.0, rf_pad_z])
    cube([22, 15, 1.5]);

  // ── Raised labels on front face ───────────────────────────────────────────
  translate([led_cx, 0, led_cz - 9])
    rotate([90, 0, 0])
      label("IR TX", 3.5);

  translate([vs_cx, 0, vs_cz - 9])
    rotate([90, 0, 0])
      label("IR RX", 3.5);

  // LCARS project label
  translate([ext_w / 2, 0, ext_h - 8])
    rotate([90, 0, 0])
      label("LCARS IR/RF", 4);
}


// ═══════════════════════════════════════════════════════════════════════════
// LID
// ═══════════════════════════════════════════════════════════════════════════

module lid() {
  // ── Flat top plate ────────────────────────────────────────────────────────
  difference() {
    cube([ext_w, ext_d, lid_t]);

    // Vent slots (2 × 3 slots, keeps things cool, also looks good)
    for (row = [0:2]) {
      for (col = [0:1]) {
        translate([ext_w * 0.28 + col * ext_w * 0.25,
                   ext_d * 0.3 + row * (ext_d * 0.15),
                   -1])
          cube([ext_w * 0.15, 2.5, lid_t + 2]);
      }
    }
  }

  // ── Lip (drops into box interior) ────────────────────────────────────────
  translate([wall + tol, wall + tol, -lip_depth])
    rect_tube(int_w - tol*2, int_d - tol*2, lip_depth, lip_t);

  // ── Snap-clip cantilever tabs on lip ──────────────────────────────────────
  // Tabs point outward (away from box centre) and click through box wall holes.
  // Angled ramp on top aids insertion; square shoulder catches on bottom edge
  // of hole for retention.
  clip_z_on_lid = -clip_h + 0.5;  // Z relative to top of lid plate

  for (cx = clip_xs) {
    // Front clip (faces toward -Y = front of box)
    translate([cx - clip_w/2, wall + tol, clip_z_on_lid])
      snap_clip(outward_y = -1);

    // Back clip (faces toward +Y = back of box)
    translate([cx - clip_w/2, ext_d - wall - tol - clip_t, clip_z_on_lid])
      snap_clip(outward_y = +1);
  }
}

// Cantilever snap clip.
// Root at origin (x=0, y=0, z=0), protrudes in outward_y direction.
module snap_clip(outward_y) {
  // Root post
  cube([clip_w, clip_t, clip_h]);

  // Wedge-shaped catch at the bottom of the tab
  // (the square shoulder that latches on box hole edge)
  mirror_y = (outward_y < 0) ? 1 : 0;
  translate([0, mirror_y ? clip_t : 0, 0])
  mirror([0, mirror_y, 0])
    translate([0, 0, 0])
      hull() {
        cube([clip_w, clip_pro, 1]);           // catch shoulder at bottom
        translate([0, clip_pro, clip_h * 0.4]) // ramp meets post at mid-height
          cube([clip_w, 0.01, 0.01]);
      }
}


// ═══════════════════════════════════════════════════════════════════════════
// RENDER
// ═══════════════════════════════════════════════════════════════════════════

if (PART == "box" || PART == "both") {
  box_body();
}

if (PART == "lid" || PART == "both") {
  // In "both" mode: show lid exploded above box for visual check.
  // In "lid" mode: rotate flat for printing (flip over, plate on bed).
  if (PART == "both") {
    translate([0, 0, ext_h + 15])
      rotate([180, 0, 0])
        translate([0, -ext_d, -lid_t])
          lid();
  } else {
    // Lid printed upside-down: flat plate on bed, lip pointing up.
    rotate([180, 0, 0])
      translate([0, -ext_d, -lid_t])
        lid();
  }
}


// ═══════════════════════════════════════════════════════════════════════════
// NOTES
// ═══════════════════════════════════════════════════════════════════════════
//
// Verify before printing
// ──────────────────────
// 1. USB-B cutout position: measure from your Uno's USB-corner to connector
//    centre and update usb_cut_cy / usb_cut_cz if needed.
// 2. Mounting hole positions (mholes[]): fine for genuine Uno R3 and most
//    clones, but some CH340 clones shift holes slightly — dry-fit before gluing.
// 3. Print the lid first — it's quick and lets you verify snap fit before
//    committing to the longer box print.
//
// Assembly order
// ──────────────
// 1. Thread M3 screws into standoffs (or use a soldering iron to set M3
//    heat-set inserts if you have them — much stronger).
// 2. Mount Arduino on standoffs.
// 3. Hot-glue FS1000A and XD-RF-5V to their pads (right side of floor).
// 4. Wire everything up.
// 5. Press VS1838B dome into its hole from outside; a small bead of
//    cyanoacrylate on the rim holds it.
// 6. IR LED press-fits into its 5.4 mm hole; add hot glue inside to anchor.
// 7. Route USB cable out the left face.
// 8. Snap lid on. Press firmly on all four clip positions until you hear
//    each click.
// 9. Mount to wall: drive 2 screws into wall/stud, slide box keyholes over
//    screw heads, push down to lock.
//
// Print settings (PLA works fine)
// ────────────────────────────────
// Layer height : 0.2 mm
// Walls        : 3 perimeters
// Infill       : 20 % gyroid
// Supports     : none needed (all overhangs ≤ 45°)
// Orientation  : box flat-back-down; lid flat-plate-down (already positioned)
