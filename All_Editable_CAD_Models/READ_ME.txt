EDITABLE PARAMETRIC CAD MODELS — OpenSCAD (.scad)

These are source CAD models, not STL meshes or STEP files. Each file is self-contained and opens the named part by default.
Open a file in OpenSCAD, edit its dimensions/parameters, render, then export STL for printing.
All dimensions are millimetres.

01 Integrated UNO: integrated flexible strap and enclosure base, plus matching separate lid.
02 Separate UNO: base, lid and separate demo strap.
03 Reference Compact: original 86 x 60 x 22 mm assembled housing option; not the UNO option.

Parameters include housing dimensions L/W/H, wall/floor/lid thickness, strap width and thickness, measured_neck, fit and closure allowances, adjustment holes, and sensor slot size/position.
When changing base dimensions, make identical changes in the matching lid file.
Each file is independent; edits are not synchronized between files.
Existing printable STL files were validated separately. Changed CAD parameters require rerendering and new geometry/fit checks.

900 mm neck input is an illustrative placeholder, not a cattle average. Strap is unmeasured and not validated for animal wear. The integrated 1080 mm long print requires flexible-material and printer-size assessment. Buckle, sensor mounting and closure are not included.
For Fusion/SolidWorks STEP workflows, these files are not STEP solids; use OpenSCAD to edit this supplied parametric source.
