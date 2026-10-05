# Clone Type 1 + Soy Sauce Panel 3 + speaker control

Support for an R36S clone that none of the stock `clone type1 panelN` folders fit.

## The device

| | |
|---|---|
| Board silk | `R36S_V20_2025_05_18` |
| Stock DTB | `rf3536k3ka.dtb` (kept in `stock/`, md5 `729058d6c81f45b264d1f88ce7fb4fc5`) |
| Stock firmware | ArkOS 2.0 (08232024) userland on the vendor kernel |

The DTB analysis tool's board gallery lists this silk as "Clone Type 3 Panel 2",
which is today's `clone type1 panel3`. That folder is built for a different
panel. Comparing the stock DTB with the ArkOS4Clone trees shows what this unit
actually is:

- **Board wiring is Clone Type 1.** Panel reset `GPIO3_B7`, LCD power `GPIO0_B5`,
  joystick mux `GPIO2` pins 12/15/16, headphone detect `GPIO2_C6`, backlight PWM
  period, SD slot settings: all identical to `clone type1 panel3`.
- **The panel is the one from `sauce panel3`.** The 420-byte init sequence is
  byte-identical; no Clone R36s entry carries it.
- **The speaker is gated by `GPIO3_A7`.** Stock drives it as `spk-con-gpio`. The
  codec's own speaker output feeds the speaker (no external-amplifier mode), but
  nothing is audible unless that pin is high.

## What is in the tree

- `boot/dArkOS/consoles/clone type1 sauce3 spk/` holds `boot.ini` and the DTB.
  The DTB keeps the name `rk3326-r36s-type1-panel3-linux.dtb` because
  `console_detect` identifies the device from that filename.
- `dtbTools/internal/console/config.go` lists it in `dtb_selector` as
  "Clone R36s -> Clone Type 1 Soy Sauce Panel 3 With Speaker Control".

The DTB is `clone type1 panel3` with these changes only:

| Node | Property | Value |
|---|---|---|
| `panel@0` | `panel-init-sequence` | from stock |
| `panel@0` | `prepare/reset/enable/disable-delay-ms` | 100 / 50 / 200 / 50 (stock) |
| `panel@0/display-timings/{original,adjust}` | clock, porches, sync | 40 MHz, h 60/2/60, v 20/4/14 (stock) |
| `pmic@20/codec` | `spk-ctl-gpios` | `<&gpio3 7 GPIO_ACTIVE_HIGH>` |
| `pmic@20/codec` | `spk-mute-delay-ms` | 50 |

Both display modes use the stock timing, about 100 Hz. `sauce panel3` runs the
same values.

### Things that were tried and are wrong for this board

- `use-ext-amplifier`: sound only reaches the headphone jack.
- Headphone detect as `GPIO_ACTIVE_HIGH` (what the stock DTB's flag suggests):
  detection is inverted and the speaker dies when headphones are unplugged. The
  Clone Type 1 value, `GPIO_ACTIVE_LOW`, is correct for this kernel.

## Files here

| File | Purpose |
|---|---|
| `make_dtb.py` | Rebuilds the DTB from `clone type1 panel3` and the stock DTB. |
| `stock/rf3536k3ka.dtb` | The unit's stock device tree, the source of the panel data. |
| `preselect_device.py` | macOS: selects a device inside a built `.img` so it boots without running `dtb_selector`. |
| `Audio Diag.sh` | On-device check. Copy to `/roms/tools`, run from the Tools menu, read `audio_diag.log`. |

## After syncing from upstream

The DTB is derived from upstream's `clone type1 panel3`. If a sync changes that
file, regenerate and commit:

```sh
contrib/clone-type1-sauce3/make_dtb.py --check   # reports whether it is stale
contrib/clone-type1-sauce3/make_dtb.py           # rewrites the console DTB
```

A sync can also conflict in `dtbTools/internal/console/config.go` if upstream
edits the entries next to this one; keep both sides.

## Building an image

Run the "ArkOS4Clone 构建和发布" workflow, download the parts from the draft
release, then:

```sh
7z x ArkOS4Clone-*.img.xz.7z.001 && xz -dk ArkOS4Clone-*.img.xz
contrib/clone-type1-sauce3/preselect_device.py ArkOS4Clone-*.img
```

If the workflow fails in "Build image" with `go: download go1.x ... stream
error`, the Go toolchain download timed out; re-run the failed job.
