# Manual recovery of a blocked Wi-Fi adapter

This is a manual recovery procedure for a Wi-Lab adapter that cannot be brought up.
It resets **one USB device**, not the USB controller or every adapter. This page
covers manual recovery; automatic reset applies to adapters detected as USB and is
described in [Architecture](architecture.md#8-quarantine-and-automatic-usb-recovery).
A successful reset does not establish or fix the underlying cause.

## Symptoms and observed case

The interface may still be listed by `ip` and `iw`, but creating a network fails
with a timeout or HTTP 500. An attempt to bring the interface up can return
`RTNETLINK answers: Connection timed out`. In one investigation, `hostapd` also
crashed while cleaning up after that timeout; the crash was not the first error.

A targeted USB reset restored one MediaTek `mt7921u` adapter in a KVM guest. Both
APs were subsequently created and verified simultaneously through Wi-Lab and
`iw`. This is an observed recovery, not a guarantee for other hardware or setups.

## Safety and preparation

- Arrange a maintenance window and prevent new Wi-Lab requests for the entire
  procedure. Stopping Wi-Lab affects the whole lab, including the other adapters.
- Check `/api/v1/status` in the authenticated web UI or Swagger and confirm
  **all** reservations are released and there are no active Wi-Lab networks.
  Ask their owners to release them; do not use the global release endpoint.
  If a release returns 503, resolve its cleanup failure before proceeding.
- Check for non-Wi-Lab users of the adapters, including externally managed APs
  and connected clients. Wi-Lab status does not report those. Do not reset a
  device in use; if ownership or activity is uncertain, stop and investigate.
- Use a separate management connection and, preferably, local or out-of-band
  console access. Confirm the adapter is not the management or upstream interface:

  ```sh
  ip -br link
  ip route show default
  iw dev
  ```

- Do not print or share API tokens, reservation IDs, WPA passwords, complete
  configuration files or unredacted logs. Failed AP creation may leave a
  `hostapd` configuration containing a password under `/tmp/wilab-hostapd/`;
  treat it as sensitive and remove it only after confirming that it is no longer
  used and that removal is authorized.
- Commands below assume Linux, systemd, `ip`, `iw`, `lsusb`, `usbreset` and
  administrator privileges. If an environment requires a sudo askpass helper,
  use `sudo -A` instead of `sudo`. Do not continue if a required command fails.

## 1. Identify and diagnose the target

Choose the **actual** interface name from `ip -br link`, `iw dev`, and the
Wi-Lab status page. The following is an example, not a default:

```sh
IFACE=wlx001122334455
ip -br link show "$IFACE"
iw dev "$IFACE" info
readlink -f "/sys/class/net/$IFACE/device"
lsusb -t
systemctl is-active wi-lab.service
journalctl -u wi-lab.service --since '15 minutes ago' --no-pager
sudo journalctl -k --since '15 minutes ago' --no-pager
```

Inspect logs locally for interface-up timeouts, USB errors, firmware messages and
`hostapd` failures. Logs can contain sensitive data; redact them before sharing.
An HTTP 500 or a `hostapd` crash alone does not prove a USB or driver problem.

## 2. Stop Wi-Lab and confirm the target is idle

Record whether the service was active. After coordinating the maintenance window
and confirming that all reservations and networks are gone, stop it:

```sh
sudo systemctl stop wi-lab.service
systemctl is-active wi-lab.service
```

Confirm the service is inactive. Recheck that no other process or client is using
the target adapter. An absent SSID, `Not connected`, or Wi-Lab reporting standby
alone is not proof that the adapter is unused. If the device is still in use or
its ownership is unclear, stop here; restore the service if it was previously
active and it is safe to do so. `systemctl is-active` normally returns a
nonzero exit status for an inactive service.

## 3. Map the interface to exactly one USB device

Run the following on the machine that owns the interface:

```sh
USB_INTERFACE=$(readlink -f "/sys/class/net/$IFACE/device")
USB_DEVICE=$(dirname "$USB_INTERFACE")
printf 'Interface path: %s\nUSB device path: %s\n' "$USB_INTERFACE" "$USB_DEVICE"
cat "$USB_DEVICE/idVendor" "$USB_DEVICE/idProduct"
cat "$USB_DEVICE/busnum" "$USB_DEVICE/devnum"
```

Confirm that the parent is the intended USB **device**, that the IDs and
bus/device numbers agree with `lsusb -t` and `lsusb`, and that no other
interface or function of that USB device is in use. If the files are missing,
the device is not a USB adapter at that path, or the mapping is ambiguous, do
not reset it. Do not use a vendor/product ID or product name as the reset
selector: identical adapters may share those values.

USB bus and device numbers can change after reconnection. Read them immediately
before the reset and verify the mapping again if anything changes:

```sh
BUS=$(cat "$USB_DEVICE/busnum")
DEVICE=$(cat "$USB_DEVICE/devnum")
lsusb -s "$BUS:$DEVICE"
printf 'Target: %03d/%03d\n' "$BUS" "$DEVICE"
```

## 4. Reset the identified device

Only after confirming the target and that it is idle:

```sh
sudo usbreset "$(printf '%03d/%03d' "$BUS" "$DEVICE")"
```

Check that the command succeeds. This resets the entire selected USB device and
may briefly remove all of its interfaces. It must not be used on a USB hub or
controller. Do not unload shared driver modules or repeatedly reset devices.

## 5. Verify the adapter and restore the service

Wait for the adapter to reappear, then inspect its name, driver and recent kernel
messages:

```sh
ip -br link
iw dev
readlink -f "/sys/class/net/$IFACE/device/driver"
sudo journalctl -k --since '2 minutes ago' --no-pager
```

If the interface name changed, do not assume Wi-Lab will find it: compare it
with the configured interface and resolve the mismatch before starting Wi-Lab.
Do not silently edit the configuration.

While Wi-Lab remains stopped and the adapter is exclusively yours, verify that
the interface can be brought up and return it to idle:

```sh
sudo timeout 15s ip link set dev "$IFACE" up
sudo timeout 15s ip link set dev "$IFACE" down
```

Run the second command only if the first succeeds. If activation still times out,
do not report the adapter as recovered. Restore the service if appropriate and
escalate the issue; other configured adapters may remain usable.

If the service was active before maintenance, start it again:

```sh
sudo systemctl start wi-lab.service
systemctl is-active wi-lab.service
```

Verify the UI and authenticated status endpoint, confirm the expected interfaces
are present and free, and inspect service logs if startup fails. Resume incoming
requests only after maintenance is complete.

## 6. Validate with Wi-Lab and an external client

During the maintenance window, reserve the recovered adapter through Wi-Lab and
create a temporary WPA2 network with a unique SSID and password. Verify its
status in Wi-Lab and with `iw dev "$IFACE" info`. Connect an external client and
check association and DHCP; check Internet access only if enabled for that test.

When multiple adapters are needed, reserve and create a network on each, verify
that they are active simultaneously, and test the required client connections.
Release only the reservations created for the test. Confirm Wi-Lab reports no
test networks or reservations remaining. A successful `iw` or API check alone
does not prove that external clients can connect.

## If recovery fails or the issue recurs

- Check the kernel and service logs around the failure, and record the interface,
  USB topology, driver, firmware, kernel and `hostapd` versions. Redact secrets.
- Compare the adapters separately and together. On a VM, compare with a test on
  the physical host and review USB passthrough and power; coordinate any physical
  unplugging with the operator. Do not assume a driver reload is equivalent to a
  successful targeted USB reset.
- Do not reset the shared controller, use broad process-killing commands, or
  continuously retry. Preserve evidence and escalate to the host administrator.

## When to use manual recovery

Manual recovery is needed if automatic recovery was not enabled, refused the
target, or exhausted its attempts. Coordinate a maintenance window before
stopping the service: this affects all clients, not just the quarantined
adapter. Quarantine is in memory; a service restart clears it but does not
repair the adapter. Follow this procedure before returning it to service.
