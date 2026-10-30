# PCBHomeFab manual

How to make a single-sided PCB at home with PCBHomeFab: from the KiCad file to the etched, drilled and cut board.
Installation and operation of the service are described in the [README](../README.md) and in
[deployment.md](deployment.md).

## 1. The process in short

1. **Design** the board in KiCad (one copper layer, B.Cu) and export it as a Gerber ZIP, or keep the `.kicad_pcb` file.
2. **Log in** (section 3) and **create a job** in the web interface: add the boards, set the copies, check the panel layout, press "Create job".
3. **Expose** the photoresist board: copy `exposure.pm3` to the printer (USB stick), print it, rinse, develop and etch.
4. **Drill and mill** on the CNC mill: one G-code program per tool, with the positioning marks as zero point.

Everything is made for a whole **panel** (German: *Nutzen*): the blank that carries all boards of one run. One
exposure and one milling run make the whole batch.

## 2. Preparing the input

PCBHomeFab takes the copper layer of the **bottom side (B.Cu)**, the board outline (**Edge.Cuts**) and the holes.

**Gerber ZIP:** a ZIP file with the B.Cu Gerber file, the Edge.Cuts Gerber file and the Excellon drill file(s) of the
KiCad plot ("Plot" and "Generate Drill Files", metric, absolute origin).

**KiCad file:** a `.kicad_pcb` file can be uploaded directly. Conditions:

- The copper zones must be **filled** in the file (press `B` in the PCB editor before saving). A file with an unfilled
  B.Cu zone is refused (`ingest.zone_not_filled`).
- Trapezoid pads and bezier curves are not supported (`ingest.unsupported_kicad`); chamfered pad corners are drawn square.

A file may hold several boards, each with its own outline in Edge.Cuts. Each outline is milled, but the file is placed
on the panel as one block.

Limits (defaults, the operator can change them): 10 MB per file, 8 files per job, 200 boards in total.

## 3. Login and your jobs

The service needs a login. Your administrator creates an account for you (username and password, at least 10
characters). Open the address of the service: you are sent to the login page, and after the login back to where you
wanted to go. The header shows your name and "Log out". The login lasts for two weeks without use; the page renews it by
itself.

**My jobs** (`/jobs`) lists all your jobs, the newest first, with the date, boards, panel size, outputs and state. "Open"
shows the job page, "Delete" removes the job and all its files for good (after a question). **Nothing is deleted
automatically.** Every account may keep a limited number of jobs (200 by default); when the limit is reached, delete jobs
you no longer need. A job is visible only to its owner; other accounts get "does not exist".

## 4. The editor ("New job")

### Adding boards

Drag one or more Gerber ZIPs or KiCad files onto the page or choose them with the file button. For every board you see
its size, the number of holes, the shape of the outline and the hole sizes. Set the number of **copies** and the order
of the boards with the controls of each row.

### Panel and spacing

| Setting | Meaning |
|---|---|
| Panel size | The blank you have: 160 x 100, 75 x 100 or 100 x 75 mm by default (the operator can add sizes). |
| Gap between boards | Space between two boards on the panel. |
| Margin to the edge | Free border around all boards. Needs at least 4.5 mm when positioning marks are on (default 5 mm). |
| Material thickness | Thickness of the board material (default 1.6 mm). The milling depth is the thickness plus the overshoot of the mill profile. |

### The panel preview

The preview shows the boards on the panel and updates while you change the settings. Two views, switched with the
buttons above the panel:

- **Design view** as in KiCad: the boards with their holes, coloured by diameter.
- **Underside**: the copper side seen from below (mirrored left to right) with tracks, pads, pours, boards and holes.
  This is how the finished copper looks when you turn the panel over.

Zoom with the **mouse wheel** (towards the pointer, up to 40 times), move with the **held middle mouse button**, reset
with a **double click**.

### Holes without a drill

Each hole gets the drill of the same diameter. Holes larger than the largest drill (1.5 mm by default) are milled with an
end mill. If the tool library has **no drill for a hole size** and the hole is not larger than the largest drill, the
editor shows a select box for that size (default: the next larger drill). Your choice is stored with the job and shown
on the job page. Without a choice the job is refused (`mill.no_drill`).

### Settings

The settings are remembered in your browser.

**Outputs:** exposure file (mask and `.pm3`) and/or drill and mill G-code. A job needs at least one.

**Exposure**

| Setting | Meaning |
|---|---|
| Printer | The printer profile (display size, resolution, file format). Details on the Machines page. |
| Exposure time | Seconds of UV light, stored in the `.pm3` file. Find the right value with a test exposure. |
| Drill holes in the mask | *Full diameter*: pads open up where the hole is (the drill hole is exposed). *Center mark only*: a small mark to centre the drill. *Pads stay solid*: no mark. |

**Calibration** (values of the printer profile, change them only after measuring a test exposure):
panel offset from the left and from the bottom of the display, and mirroring of the image in X.

**Milling**

| Setting | Meaning |
|---|---|
| Mill | The mill profile (spindle, safe height, tool change height, tab size). |
| How the panel is turned over | The panel is exposed with the copper side down and milled with the copper side up. *Around the Y axis (mirror X)* is the default; the G-code coordinates are then the view onto the copper side. |
| Tabs | Small bridges that hold the boards in the panel when the outline is cut. Break them by hand afterwards. |

**Positioning marks** (default on): see the next section.

"Create job" uploads the files and leads to the job page.

## 5. Positioning marks

The panel is never at exactly the same place on the mill and not exactly square. Two **marks** on the copper layer solve
that:

- Two marks stand diagonally opposite in the margin. Each is made of two quarter circles of copper that face each other
  inside a free disc. The **centre** is where the tips touch; it stays in place even if the copper is etched too much.
- After turning the panel over, one mark is at the **lower left** and one at the **upper right**. The lower left mark is
  **X0 Y0** of every G-code program. It is set as close to the boards as possible.
- The upper right mark has the coordinates written on the job page, in the header of each program and in
  `programs.json` (for example X 156, Y 96 on a 160 x 100 mm panel).
- With "Coordinates next to the positioning marks" (default on) the coordinates (`X0 Y0`, `X156 Y96`) are exposed as
  text next to each mark. They are mirrored so that they read correctly on the finished copper.

On the mill: jog the tool to the centre of the lower left mark and set X0 Y0 there. Move to the upper right mark and
check its position. If it is off, the panel is turned; turn it until both marks fit.

## 6. The job page

The page shows the progress ("This page updates itself"). The job stays in "My jobs" until you delete it; the address
`/jobs/<id>` opens it again, after the login.

| Section | Content |
|---|---|
| Boards, outputs, panel | The data of the job. |
| Positioning marks | Where the marks are and how to use them. |
| Drill assignment | Your choice for hole sizes without a drill of their own. |
| Exposure | Picture of the mask and the downloads `exposure.pm3` and `mask.png`. |
| Drill and mill | Picture of the panel with outlines and holes (colour = diameter) and one download per G-code program. |
| 3D simulation | See section 9. |
| Job description | The PDF, see section 10. |
| All files | Everything in one ZIP. |

## 7. Exposure

The mask is made for **positive photoresist**: **white = exposed = the copper is etched away**, black = the copper
stays. Copper pours are kept automatically.

1. Copy `exposure.pm3` to a USB stick and put it into the printer. The file is read by the printer directly, it is not
   opened in Photon Workshop.
2. Put the resist-coated panel on the display with the copper side **down**. The mask is the top view of B.Cu as it is
   (not mirrored); seen from the copper side the etched copper is its mirror image, so text on B.Cu reads correctly.
3. Print (expose), then develop and etch as usual for your photoresist.

The panel sits in a frame on the display at the offsets set in the calibration settings (starting values 1.8 mm from
the left and 0.8 mm from the bottom, to be checked on your printer). **Calibration:** make a test exposure and measure
where the copper ends up; correct the offsets and the mirroring in the settings.

## 8. Drilling and milling

The job contains **one G-code program per tool**, numbered in the order in which to run them: first the drills, then the
end mills for large holes, cutouts and the board outlines. The G-code is made for GRBL.

Before the first run: the spindle speed in the programs is the `S` value; `$30` of GRBL must match it (20,000 rpm needs
`$30=20000`).

For each program:

1. Load it into your sender (any GRBL sender).
2. The program moves to the **tool change position** (X0 Y0, high up) and pauses with `M0`, spindle off.
3. Insert the tool named in the program, set **Z0 to the panel surface**, and resume the program.
4. At the end it parks at the tool change position with the spindle off. Continue with the next program.

X0 Y0 is the lower left positioning mark, see section 5. Without marks, X0 Y0 is the panel origin of the mill profile (`offset_x_mm`, `offset_y_mm` on the Machines page).

- **Holes** are drilled with explicit moves (GRBL has no canned cycles); deep holes are drilled in steps (pecking).
- **Outlines** are milled along the real Edge.Cuts contour, offset by the radius of the end mill, with the cutting depth
  of thickness plus overshoot. With tabs on, the boards stay connected at small bridges.
- The cutting values of the tool library are **starting values**. Tune feed, plunge and depth on your mill.

## 9. 3D simulation

The job page shows the drill and mill paths in 3D, to check them before the mill runs.

- **Turn** with the mouse, **move** with the middle mouse button, **zoom** with the wheel or the buttons. With the view
  in focus: arrow keys turn, `+` and `-` zoom, space plays and stops.
- Show **one program** or **all programs in order**, play, pause, restart, change the speed or drag the position slider.
- *Depth exaggeration* makes the depth visible; *rapid moves* can be shown or hidden; *copper* shows the copper of the
  boards faintly on the panel.
- The time is estimated from the feed rates; rapid moves are assumed at 1500 mm/min. Hours are shown from 60 minutes on.

## 10. Job description (PDF)

The link "Job description (PDF)" on the job page opens a PDF in the language of the page. It holds:

- the header data of the job (boards, outputs, drill assignment, marks, panel),
- the exposure mask and the drill and mill view with a legend of the hole sizes,
- the tools with the program (`.nc` file) for each, the number of holes and contours, and the run time,
- the production time for drilling and milling (**without** exposure).

The run times are estimated from the G-code. They do not include the pause for the tool change, setting Z0 or the
acceleration of the machine, so the real time is somewhat longer. Jobs made before version 0.23.0 have no times; their
PDF has no tool table. The PDF is also in the ZIP of "All files".

## 11. Tools and machines

**Tools** (`/tools`): the tool library the G-code is made for. By default drills from 0.6 to 1.5 mm in 0.1 mm steps and
end mills of 1, 2 and 3 mm, with spindle speed, feed, plunge feed and peck depth. The operator can replace the library
with an own file, see [deployment.md](deployment.md).

**Machines** (`/machines`): the parameters of the printer and mill profiles (display, resolution, calibration, lift,
spindle, safe height, tool change height, tabs, panel sizes).

### Maintaining the tool library

The library is a TOML file. The built-in file is `services/mill/src/mill/data/tools.toml`; your own file **replaces it
completely**. Get a copy, edit it, put it into the `mill_data` volume and point `mill` to it (the full commands are in
[deployment.md](deployment.md#own-tool-library)):

```bash
docker compose run --rm --no-deps mill python -c "from mill.tools import default_text; print(default_text())" > tools.toml
```

Structure of the file:

```toml
[defaults.drill]            # applies to every drill that does not set the value itself
spindle_rpm = 20000
plunge_feed = 50            # mm/min
peck_mm = 0.7               # depth per step, 0 = drill in one go

[defaults.endmill]
spindle_rpm = 20000
feed = 70                   # mm/min in the material
plunge_feed = 50            # mm/min
step_down_mm = 0.4          # depth per pass

[[tool]]                    # one entry per drill or end mill
id = "drill-0.6"            # unique
kind = "drill"              # "drill" or "endmill"
diameter_mm = 0.6
peck_mm = 0.5               # overrides the default for this tool
# enabled = false           # hides the tool without deleting it; name and notes are optional texts
```

- **Add a tool:** a new `[[tool]]` entry with a unique `id`, the `kind` and `diameter_mm`.
- **Change cutting values:** for all tools of a kind in `[defaults.*]`, for one tool in its entry.
- **Remove a tool:** set `enabled = false` (or delete the entry). Holes of a size without a drill are then refused
  (`mill.no_drill`) or need an assignment in the editor.
- A wrong file (invalid TOML, missing or unknown keys, a number that is not greater than zero) is refused with a message
  that names the entry.
- The file is read for each request: the next job uses the change without a restart. `/tools` shows the library in use
  and its source.
- The spindle speed of a tool may not be higher than `max_spindle_rpm` of the mill profile.

Hole sizes: a hole gets the drill of the same diameter (tolerance 0.02 mm); holes larger than the largest drill are
milled with the end mill. The outline is cut with the end mill named by `outline_endmill_mm` of the mill profile.

### Maintaining machine data

The printer and mill profiles (page `/machines`) are part of the program, there is **no configuration file** for them yet.
Two ways to change them:

**Per job, in the editor:** the calibration of the printer (panel offset from the left and from the bottom, mirroring in
X), exposure time, how the panel is turned over, tabs and the panel size. The editor remembers these in the browser; they
are stored with each job.

**For everyone, in the source:** change the values in
`services/exposure/src/exposure/profiles.py` (printers) or `services/mill/src/mill/profiles.py` (mills), run
`scripts/check_service.sh exposure` or `mill`, and rebuild: `docker compose up -d --build`. A new machine is another entry
in `PRINTERS` or `MILLS` with its own id.

| Profile | Value | Meaning |
|---|---|---|
| Printer | `resolution_x/y`, `display_width/height_mm` | Display of the printer; the pixel size follows (40 µm on the Photon M3). |
| Printer | `frame_left_mm`, `frame_bottom_mm` | Where the lower left corner of the panel lies on the display (calibration). |
| Printer | `mirror_x` | Mirror the mask. Off by default, see section 7. |
| Printer | `default_exposure_s`, lift and retract values | Defaults written to the `.pm3` file. |
| Printer | `machine_name` and the `machine_*` values | The machine table of the `.pm3` file. Photon Workshop rejects unknown printer names, so keep the values of a file the printer wrote. |
| Mill | `max_spindle_rpm` | Highest spindle speed; it must match `$30` of GRBL. |
| Mill | `outline_endmill_mm` | End mill (diameter in the tool library) that cuts the outlines. |
| Mill | `safe_z_mm`, `tool_change_z_mm` | Travel height and height of the tool change position. |
| Mill | `spindle_spinup_s` | Wait after switching the spindle on. |
| Mill | `drill_overshoot_mm`, `mill_overshoot_mm` | How far the tool goes below the board (default 0.15 mm). |
| Mill | `tab_width_mm`, `tab_height_mm`, `tabs` | Bridges that hold the boards in the panel. |
| Mill | `flip` | How the panel is turned over: `x`, `y` or `none`. |
| Mill | `offset_x_mm`, `offset_y_mm` | Position of the panel's lower left corner in machine coordinates (without marks). |

The panel sizes are data of the `jobs` service: an own list in a TOML file, see
[deployment.md](deployment.md#own-panel-sizes).

Jobs keep what they were made with: a change of a tool or profile applies to new jobs only.

Language: the switch in the header changes between English and German; the first visit follows the browser language.

## 12. REST API

The same functions are available without the web interface. The gateway publishes the `jobs` service under `/api`.
Every call needs the access token of an account in the header `Authorization: Bearer <token>`; without it the answer is
`401`. Scripts get a token from the login with the client `pcbhomefab-cli` (valid for 15 minutes):

```bash
TOKEN=$(curl -s -d client_id=pcbhomefab-cli -d grant_type=password -d username=thomas --data-urlencode password='...' \
    http://localhost/auth/realms/pcbhomefab/protocol/openid-connect/token | python3 -c 'import json,sys; print(json.load(sys.stdin)["access_token"])')
AUTH="Authorization: Bearer $TOKEN"
curl -H "$AUTH" -F boards=@base.zip -F boards=@node.zip -F counts=1 -F counts=15 -F panel=160x100 -F exposure_s=120 http://localhost/api/v1/jobs
curl -H "$AUTH" http://localhost/api/v1/jobs                        # your jobs, newest first (limit, offset)
curl -H "$AUTH" http://localhost/api/v1/jobs/<id>                   # status and file list
curl -H "$AUTH" -O http://localhost/api/v1/jobs/<id>/files/exposure.pm3
curl -H "$AUTH" -o job.pdf "http://localhost/api/v1/jobs/<id>/report.pdf?lang=en"
curl -H "$AUTH" -o all.zip "http://localhost/api/v1/jobs/<id>/archive?lang=en"
curl -H "$AUTH" -X DELETE http://localhost/api/v1/jobs/<id>         # delete a job and its files
```

**OpenAPI:** the running service describes its API at `GET /api/openapi.json` (generated by the `jobs` service, for
tools such as client generators). The maintained description of the public API, with the parameters and error codes,
is [contracts/jobs.openapi.yaml](../contracts/jobs.openapi.yaml); the other contracts are in
[contracts/](../contracts/). `GET /api/v1/panels`, `/api/v1/profiles` and `/api/v1/tools` list the choices.

## 13. Troubleshooting

| Message or problem | Cause and remedy |
|---|---|
| `ingest.zone_not_filled` | Fill the zones in KiCad (`B`) and save the file again. |
| `ingest.unsupported_kicad` | The file has trapezoid pads or bezier curves. Export a Gerber ZIP instead. |
| `mill.no_drill` | No drill for a hole size. Choose a drill in the select box of the editor, or add the drill to the tool library. |
| `jobs.invalid_marks` | The margin is below 4.5 mm. Increase the margin or switch the marks off. |
| `exposure.panel_too_large` | The panel and the offsets do not fit on the display of the printer. |
| Too many requests | The operator limits the number of jobs per hour. Wait and try again. |
| The job page says it does not exist | The link is wrong, the job was deleted, or it belongs to another account. |
| `jobs.quota_exceeded` | You have reached the limit of jobs of your account. Delete jobs you no longer need. |
| `jobs.unauthorized` (401) | No login, or it has expired. The web pages log in again by themselves; scripts need a new token. |
| The login page does not accept the password | Five wrong tries lock the account for a while. Ask the administrator. |
| The page shows old content after an update | Reload the page (Ctrl+F5). |
