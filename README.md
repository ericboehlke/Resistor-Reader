# Resistor-Reader

A project to read the color code on resistors

## Development

This project uses [uv](https://github.com/astral-sh/uv) for dependency
management and [flit](https://flit.pypa.io) as the build backend.

Install the dependencies:

```bash
uv sync
```

Run the tests:

```bash
uv run pytest
```

Build a distribution:

```bash
uv build
```


## Ansible Examples

### Password login only

```bash
sudo mount /dev/sdX1 /media/eric/bootfs
sudo mount /dev/sdX2 /media/eric/rootfs

ansible-playbook -i localhost, -c local pi_usb_gadget.yml \
  -e bootfs_mount=/media/eric/bootfs \
  -e rootfs_mount=/media/eric/rootfs \
  -e username=pi \
  -e password='mypassword'
```

### Key login only

```bash
sudo mount /dev/sdX1 /media/eric/bootfs
sudo mount /dev/sdX2 /media/eric/rootfs

ansible-playbook -i localhost, -c local pi_usb_gadget.yml \
  -e bootfs_mount=/media/eric/bootfs \
  -e rootfs_mount=/media/eric/rootfs \
  -e username=pi \
  -e ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"
```

### Both password and key login

```bash
sudo mount /dev/sdX1 /media/eric/bootfs
sudo mount /dev/sdX2 /media/eric/rootfs

ansible-playbook -i localhost, -c local pi_usb_gadget.yml \
  -e bootfs_mount=/media/eric/bootfs \
  -e rootfs_mount=/media/eric/rootfs \
  -e username=pi \
  -e password='mypassword' \
  -e ssh_public_key="$(cat ~/.ssh/id_rsa.pub)"
```


# Install
New raspbian lite 32 bit
connect to usb ethernet
sudo apt update
sudo apt full-upgrade
sudo apt install git python3-picamera2
curl -LsSf https://astral.sh/uv/install.sh | sh
copy ssh keys
git clone git@github.com:ericboehlke/Resistor-Reader.git
