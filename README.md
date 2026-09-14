# Wanke Cloud USB HID Web Waker

[English](README.md) | [简体中文](README.zh-CN.md)

A minimal Docker service running on an Armbian-powered Wanke Cloud (OneCloud). Click a button on a web page and it wakes another machine over USB OTG by emulating a USB keyboard.

```
Browser ──HTTP──> container (Flask) ──reports──> /dev/hidg0 ──USB OTG──> target machine
```

## Hardware

| Item | Notes |
|---|---|
| Wanke Cloud | with Armbian installed |
| Cable | see "Cable selection" below |
| Which port | **the USB port next to the HDMI** is the OTG (device mode) port; the one next to the network jack is a host port |

### Cable selection

One rule decides everything: the cable must let **the target machine act as the host** (it is the USB host) and **the Wanke Cloud act as the device** (it emulates a keyboard). Get the direction wrong and the keyboard will never be enumerated.

#### First choice: a USB-A male-to-male cable

**The cable you already used to flash the box can be reused** — no need to buy another one. The way the flashing guides tell you to plug it in (one end into your PC, the other into **the USB port next to the HDMI**) is exactly the topology this project needs: PC/target is the host, the Wanke Cloud is the device.

- It must be a **data cable** with four conductors: VBUS / GND / D+ / D-. A charge-only cable has just two conductors and no D+/D-, and will never work. If you flashed the box with it successfully, its D+/D- lines are fine.
- Do not use a "PC-to-PC transfer cable" with a chip in the middle — those are active cables, not straight-through.
- Use the same port you flashed with: **the one next to the HDMI**. The other USB port is a plain host port and nothing will happen on it.

One caveat: successfully flashing only proves that the D+/D- lines of that USB-A port are wired to the SoC's USB device controller (via Amlogic mask ROM mode). It does **not** prove that Linux can drive dwc2 in peripheral mode, so "Step 0" below is still required.

#### Target machine has a USB-C port: add an adapter

**A plain A-to-C cable will not work.** An A-to-C cable has a 56 kΩ pull-up resistor (Rp) soldered inside; its job is to tell the target's C port that "a legacy host is attached on the other side", so the target's C port makes itself a **device**. But we need it to be the **host**. The result is two devices and no enumeration; and if the target's port is a host-only port, both sides present Rp and the port simply decides nothing is plugged in.

The correct setup adds a **C-male to A-female OTG adapter** (containing a 5.1 kΩ pull-down, Rd — the kind sold for plugging a USB stick or a mouse into a phone or laptop):

```
Wanke Cloud USB-A ──A-to-A cable──> [ C-male to A-female OTG adapter ] ──> target USB-C port
```

Buying and troubleshooting:

- Pick an adapter explicitly marked **OTG / supports peripherals**. A charge-only adapter may have no resistor inside at all.
- If nothing happens, **flip the C plug over** and retry — cheap adapters may only have a resistor on one CC pin, and USB-C uses different pins depending on orientation.
- The target's C port must be a host/data port (desktop and laptop ports are normally fine); a charge-only port will not work.

#### Dealing with VBUS back-feed

An A-to-A cable connects VBUS at both ends, so the target may feed power back and make the Wanke Cloud behave strangely. Two options:

- Cut the red wire (VCC) inside the cable, keeping only D+/D- and GND;
- or put a USB hub with a physical power switch in between and keep it off while connecting.

Decision rule: **if the Wanke Cloud cannot see the target after you cut VCC** (`cat /sys/class/udc/*/state` stays at `not attached`), that port needs VBUS to establish the session — so do not cut the wire, use the switched-hub approach instead.

Also: the SoC has only 6 USB OTG endpoints in total. This project's keyboard uses 2, which is enough but not generous.

## Step 0: verify OTG support first

If this step fails, the web layer is pointless. Do it first.

```bash
ls /sys/class/udc/
#   Expect one entry (e.g. c9040000.usb). Empty means dwc2 is not in peripheral mode.

cat /proc/device-tree/soc/usb@c9040000/dr_mode 2>/dev/null   # expect otg or peripheral

zcat /proc/config.gz 2>/dev/null \
  | grep -E 'CONFIG_USB_CONFIGFS=|CONFIG_USB_CONFIGFS_F_HID|CONFIG_USB_DWC2|CONFIGFS_FS'

modinfo usb_f_hid 2>/dev/null | head -5

# Is the remote wakeup patch present? (usually not, and that is normal)
ls /sys/module/usb_f_hid/parameters/ 2>/dev/null
```

If `/sys/class/udc/` is empty, you need dwc2 loaded in peripheral mode: either edit `overlays=` / `extraargs=` in `/boot/armbianEnv.txt`, or take the device tree from the One-KVM Wanke Cloud image, which already has it configured. **Do not `apt upgrade` the kernel or device tree** — that breaks OTG.

## Deployment

### 1. Host-side gadget

```bash
sudo install -m 0755 host/setup-hid-gadget.sh host/teardown-hid-gadget.sh host/verify-hid.sh /usr/local/sbin/
sudo install -m 0644 host/i18n.sh /usr/local/sbin/
sudo install -m 0644 host/hid-gadget.service /etc/systemd/system/
sudo systemctl enable --now hid-gadget.service
```

`hid-gadget.service` sets `Before=docker.service` so that `/dev/hidg0` exists by the time the container starts.

### 2. Verify the bare hardware link

```bash
sudo /usr/local/sbin/verify-hid.sh
```

It writes a single Enter to `/dev/hidg0` with Docker out of the picture. If the target reacts, the wiring is right and the gadget is alive.

### 3. Start the container

```bash
cp .env.example .env
# change SECRET_KEY (openssl rand -hex 32) and APP_PASSWORD
docker compose up -d --build
```

Open `http://<wanke-cloud-ip>:8080` in a browser and log in with the credentials from `.env`.

## The three wake modes

| Mode | Behaviour | When to use |
|---|---|---|
| Key only | sends a key report only | sleep / lock screen / screen off — most reliable |
| Signal only | sends a wake signal, no keystroke at all | when you want to wake it without leaving input behind |
| Signal + key | signal first, then the key | default, highest chance of success |

You can also set defaults in `.env` (`WAKE_MODE` / `WAKE_KEY` / `WAKE_REPEAT`); the choice in the web UI only affects the current request.

The API contract:

- `POST /api/wake` takes a JSON **object**. Anything else — an array, a bare string, malformed JSON, an empty body with `Content-Type: application/json` — is a 400, and never triggers a wake.
- A wrong input (unknown key or mode, a repeat count outside 1-5, a key longer than 32 characters) is a **400**. Only device trouble (no `/dev/hidg0`, gadget disabled by the host) is a **503**, so the two are distinguishable in monitoring.
- `lang` and `repeat` may be omitted, `null` or `""` to mean "use the default". A `repeat` that is a bool, float, object or array is a 400 rather than being silently coerced.

Keys support chord syntax such as `ctrl+enter`, `ctrl+shift+enter`, `alt+enter`. From the command line:

```bash
# Log in first to get the session cookie and the CSRF token
curl -s -c jar.txt http://<IP>:8080/login -o /dev/null
TOKEN=$(grep csrf jar.txt | awk '{print $7}')
curl -s -b jar.txt -c jar.txt -d "username=admin&password=xxx&_csrf=$TOKEN" http://<IP>:8080/login -o /dev/null
curl -s -b jar.txt -H "X-CSRF-Token: $TOKEN" http://<IP>:8080/api/wake -H 'Content-Type: application/json' -d '{"key":"enter"}'
```

## Language

The web UI, the API and the host-side shell scripts are bilingual (English / Simplified Chinese).

**Web and API.** Each request picks a language in this order:

1. an explicit `lang` parameter — query string (`?lang=zh-CN`), form field, JSON body field, or the `X-Lang` header. This is the manual choice and it is **stored in a `lang` cookie**, so later requests keep it;
2. the `lang` cookie left by an earlier manual choice;
3. the system language, probed from the browser's `Accept-Language`;
4. the `APP_LANG` container variable, for callers that have no system language at all (curl, cron);
5. English, always there as the last resort.

A language merely detected from the browser is never written to the cookie, so it stays free to follow the browser. Clearing your session does not clear the language cookie.

**Shell scripts.** `setup-hid-gadget.sh`, `teardown-hid-gadget.sh` and `verify-hid.sh` take `--lang en|zh-CN`. Without it they follow the system locale (`LC_ALL` / `LC_MESSAGES` / `LANG`) and fall back to English:

```bash
sudo /usr/local/sbin/verify-hid.sh --lang zh-CN
```

Supported values are `en` and `zh-CN` in all three places; any other Chinese variant (`zh`, `zh-Hans`, `zh_CN`) normalises to `zh-CN`.

```bash
curl -s -b jar.txt -H "X-CSRF-Token: $TOKEN" -H "X-Lang: zh-CN" \
  http://<IP>:8080/api/wake -H 'Content-Type: application/json' -d '{"key":"enter"}'
```

Responses echo the resolved language as `lang`, and both `steps` and `warnings` come back already translated.

## Verification checklist

| Layer | Command | Expected |
|---|---|---|
| Kernel | `ls /sys/class/udc/` | one entry |
| Gadget | `cat /sys/class/udc/*/state` | `configured` while the target is on |
| Gadget | `ls -l /dev/hidg0` | character device exists |
| Hardware | `sudo /usr/local/sbin/verify-hid.sh` | target receives one Enter |
| Container | `docker compose ps` / `docker compose logs` | running, no traceback |
| Auth | log in with a wrong password | error shown, nothing leaked |
| Function | click "Wake target device" in the UI | target wakes up |
| Degradation | click after unplugging the A-to-A cable | page explains why (failure or "bus suspended"), service does not crash |

## Known limitations

1. **Waking from S4/S5 (hibernate/shutdown) is not guaranteed.** Mainline `f_hid` neither calls `usb_gadget_wakeup()` nor has a `wakeup_on_write` parameter (that is a downstream JetKVM patch), so on an unpatched kernel the "signal only" path degrades to "send an empty report" and says so in the UI. Whether it can wake the machine then depends on the target's BIOS supporting "USB keyboard wake". S3 sleep / lock screen / screen off with "key only" is basically fine.
2. To fix limitation 1 properly there are two routes: patch the kernel with `wakeup_on_write`; or set `ENABLE_UDC_REBIND=1` in `.env` and uncomment the `/sys/kernel/config` volume in `docker-compose.yml` — signal mode then unbinds and rebinds the UDC, the equivalent of replugging the keyboard, which is the most effective thing against a port that still has power.
3. **`f_hid` has a single request slot on its IN endpoint**, so a suspended bus can only ever hold one report. On a sleeping target, the empty report of "signal + key" therefore occupies the slot and the key press cannot be queued at all; prefer "key only" when the wake rate matters. The program does not fail because of this — it surfaces the actual situation as a warning in the UI.
4. **One UDC can only be bound to one gadget at a time.** If you install One-KVM later, it will fight this project over the UDC.
5. The Wanke Cloud is armv7 (32-bit). If `python:3.12-slim` has no arm/v7 variant to pull, change the first line of the `Dockerfile` to `python:3.11-slim`.
6. The container runs as root: `/dev/hidg0` is a root-owned character device and this is the simplest thing for a home appliance. `privileged` is not used.
7. **There is no TLS.** Out of the box the app speaks plain HTTP, so the password and the session cookie travel in the clear on the LAN. If you expose it beyond your own network, put a TLS-terminating reverse proxy in front and set `COOKIE_SECURE=1` so both cookies are marked `Secure`. Note that behind a proxy every request appears to come from the proxy's address, which also collapses the per-source login throttle — enable `ProxyFix` only if you trust the proxy to set `X-Forwarded-For`.
8. There is no rate limit on `/api/wake`, deliberately: clicking twice quickly is the documented recovery when the first key press does not register. Protect it with the password and the network, not with a limiter.

## Project layout

```
app.py                      Flask app: login, CSRF, pages and API
hid.py                      HID reports, key map, the three wake modes
i18n.py                     Language resolution and message lookup
locales/                    en.json / zh-CN.json message catalogs
templates/ static/          Pages and stylesheet
Dockerfile docker-compose.yml
requirements-dev.txt        pytest, for running the tests
tests/                      pytest suite plus the two bash suites
host/setup-hid-gadget.sh    Idempotent configfs gadget creation
host/teardown-hid-gadget.sh
host/verify-hid.sh          Hardware link check without Docker
host/i18n.sh                Message catalog shared by the host scripts
host/hid-gadget.service     systemd unit, Before=docker.service
README.md / README.zh-CN.md
LICENSE                     MIT
```

## Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Container will not start, `/dev/hidg0` not found | the gadget is not bound. Check `systemctl status hid-gadget`, or run the setup script by hand |
| Setup script reports `/sys/class/udc/ 为空` | dwc2 is not in peripheral mode, see "Step 0" |
| `cat /sys/class/udc/*/state` stays at `not attached` | the cable is in a plain host port (use **the one next to the HDMI**); or it is a charge-only cable with no D+/D-; or you cut VCC and this port needs VBUS to establish the session |
| Target has a USB-C port and an A-to-C cable does nothing | the roles are reversed: an A-to-C cable makes the target's C port a device. Use a **C-male to A-female OTG adapter**, see "Cable selection" |
| The adapter is connected but the keyboard is still not recognised | the adapter may have no Rd, or a resistor on only one CC pin. Flip the C plug over and retry |
| Web UI returns 503 "HID device unusable (…)" | target powered off, A-to-A cable not seated, or it just went through a bus reset — retry in a moment |
| Message "the target is very likely asleep" | normal, not a failure: once the bus is suspended the host stops polling the endpoint, so the report cannot be collected. The press report is still queued, and the key stays held after wake — **click once more to reset it** |
| The UI shows "unknown" for the USB link state | `/sys/class/udc` is not mounted; wake-up still works |
| Binding fails with too few endpoints | add `echo 1 > functions/hid.usb0/no_out_endpoint` to the setup script to drop the OUT endpoint |

## Testing

The tests live in `tests/` and need no hardware: the HID device is replaced by an ordinary file, and the shell suites exercise the host scripts as far as they can without configfs.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
pytest
```

`pytest` runs everything, including the two bash suites (`tests/host_scripts.sh` and `tests/host_i18n.sh`) through a small wrapper; those are skipped automatically when bash is unavailable.

## License

This project is licensed under the [MIT License](LICENSE).
