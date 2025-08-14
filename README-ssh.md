# SSH into Raspberry Pi Zero over USB

## Requirements
- Raspberry Pi Zero / Zero W
- Micro-USB **data-capable** cable (not charge-only)
- SD card prepared with the Ansible playbook (`pi_usb_gadget.yml`)

---

## Steps

1. **Connect**
   - Plug the cable into the Pi Zero’s **USB** port (closest to the middle), **not** the “PWR IN” port.
   - Connect the other end to your computer.
   - If your host can’t power the Pi reliably over the data port, use the “PWR IN” port for power and the “USB” port for data.

2. **Boot the Pi**
   - Insert the prepared SD card and power on.

3. **Check for USB Ethernet interface**
   ```bash
   ip a
   ```

Look for `usb0` or `enx<something>`.
To watch for it in real time:

```bash
dmesg --follow
```

4. **Assign IP to host (if DHCP not automatic)**

   ```bash
   sudo ip addr add 169.254.64.1/16 dev usb0
   sudo ip link set usb0 up
   ```

5. **SSH into the Pi**

   * Link-local IP:

     ```bash
     ssh pi@169.254.64.2
     ```
   * Or via mDNS (if supported on your host):

     ```bash
     ssh pi@raspberrypi.local
     ```

   Use the password or SSH key configured in the playbook.

---

## Troubleshooting

* **No `usb0` appears** → Check cable type and correct USB port on the Pi.
* **`Permission denied (publickey)`** → The Pi is set for key-only login; re-run the playbook with a password or public key.
* **Cannot reach `169.254.64.2`** → Run:

  ```bash
  arp -an
  ```

  to discover the Pi’s actual link-local IP.

