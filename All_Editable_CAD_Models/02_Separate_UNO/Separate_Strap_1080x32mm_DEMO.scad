// Millimetres. Render selected part (F6), then export STL.
// Demonstration sizing only: replace measured_neck with a measured circumference.
part = "strap"; // base, lid, strap, assembly, exploded
uno = true; // true: 108x78x32; false: reference 86x60x22
measured_neck = 0; // 0 means UNMEASURED
demo_neck = 900; // illustrative only, NOT a cattle average
fit_allowance = 40; // must be assessed for the animal
closure_allowance = 140; // must match chosen hardware
strap_width=32;
strap_thickness=2.5;
adjustment_pitch=15;
adjustment_holes=9;
sensor_slot_length=12;
sensor_slot_width=8;
sensor_slot_x=0;
sensor_slot_y=22; // off the central 32mm strap path
L=uno?108:86; W=uno?78:60; H=uno?32:22;
wall=2.4; floor=2.4; lid_thickness=2; B=H-lid_thickness;
C=(measured_neck>0?measured_neck:demo_neck)+fit_allowance;
blank_length=C+closure_allowance;
$fn=64;
module rounded(l,w,h,r) {
  linear_extrude(h) hull()
    for(x=[-l/2+r,l/2-r],y=[-w/2+r,w/2-r])
      translate([x,y]) circle(r);
}
module posts() { for(x=[-L/2+8,L/2-8],y=[-W/2+8,W/2-8]) translate([x,y,0]) children(); }
module base() {
  difference() {
    union() {
      difference() {
        rounded(L,W,B,7);
        translate([0,0,floor]) rounded(L-2*wall,W-2*wall,B,4.6);
      }
      posts() translate([0,0,floor]) cylinder(h=B-floor,r=4.5);
      for(x=[-L/2-4,L/2+4]) translate([x,0,0]) difference() {
        rounded(14,strap_width+12,4,4);
        translate([0,0,-1]) rounded(6,strap_width+2,6,2);
      }
    }
    posts() translate([0,0,B-10]) cylinder(h=11,r=1.25);
    translate([sensor_slot_x,sensor_slot_y,-1]) rounded(sensor_slot_length,sensor_slot_width,floor+2,1.5);
  }
}
module lid() { difference() {
  rounded(L,W,lid_thickness,7);
  posts() translate([0,0,-1]) cylinder(h=lid_thickness+2,r=1.65);
} }
module strap() { difference() {
  rounded(blank_length,strap_width,strap_thickness,6);
  for(i=[0:adjustment_holes-1]) translate([blank_length/2-20-i*adjustment_pitch,0,-1]) cylinder(h=strap_thickness+2,r=2.5);
} }
if(part=="base") base();
if(part=="lid") lid();
if(part=="strap") strap();
if(part=="exploded") { color("SlateGray") base(); color("LightBlue") translate([0,0,B+12]) lid(); }
if(part=="assembly") {
  // Visualization only: no functional buckle or release mechanism.
  R=C/(2*PI);
  color("Olive") difference() { cylinder(h=strap_width,r=R+strap_thickness); translate([0,0,-1]) cylinder(h=strap_width+2,r=R); }
  translate([0,-R-strap_thickness,strap_width/2]) rotate([90,0,0]) {
    color("SlateGray") base(); color("LightBlue") translate([0,0,B]) lid();
  }
}
