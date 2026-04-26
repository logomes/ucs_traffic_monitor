# SOPS-based credentials setup (fork-only)

This guide covers the optional SOPS+age layer used in the internal
fork. Upstream users can stop at the env-var configuration described
in the main README.

## Why this layer exists

VM snapshots in this deployment go to external backup storage. A
plaintext `creds.env` on disk would leak credentials in any captured
snapshot. SOPS+age encrypts credentials in a YAML committable to git;
the matching private key lives only on the production VM and is
explicitly excluded from backups.

## Bootstrap (one-time per environment)

### 1. Install SOPS and age

```sh
# Arch / CachyOS
sudo pacman -S sops age

# Debian / Ubuntu (>=22.04)
sudo apt install sops age
```

### 2. Generate the age key on the VM

```sh
sudo install -d -m 0700 /etc/utm
sudo age-keygen -o /etc/utm/age.key
sudo chmod 600 /etc/utm/age.key
sudo chown root:root /etc/utm/age.key
```

Capture the public key:

```sh
sudo grep '^# public key:' /etc/utm/age.key
# example: # public key: age1xyz...
```

### 3. Update the repo's .sops.yaml

Edit `secrets/.sops.yaml` and replace the placeholder public key
with the one captured in the previous step. Commit and push.

### 4. Create the encrypted credentials file

On a workstation with the age private key (or directly on the VM):

```sh
cp secrets/credentials.sops.yaml.example secrets/credentials.sops.yaml
$EDITOR secrets/credentials.sops.yaml   # fill in real values

# Encrypt in place
sops -e -i secrets/credentials.sops.yaml

# Verify the password fields became ENC[...]
grep password secrets/credentials.sops.yaml
```

Commit `credentials.sops.yaml` to the repo. The cleartext form of
the file should never be committed.

### 5. Deploy on the VM

```sh
sudo install -d -m 0700 -o root -g root /etc/utm
sudo cp secrets/credentials.sops.yaml /etc/utm/credentials.sops.yaml
sudo cp bin/utm-decrypt-creds.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/utm-decrypt-creds.sh
sudo cp systemd/utm-creds.service /etc/systemd/system/
sudo cp systemd/utm.service.example /etc/systemd/system/utm.service
# Edit utm.service: change EnvironmentFile to /run/utm/creds.env
# Add After=utm-creds.service and Requires=utm-creds.service under [Unit]
sudo systemctl daemon-reload
sudo systemctl enable --now utm-creds.service utm.service
sudo systemctl status utm.service
```

### 6. Exclude age.key from backups

Coordinate with the infrastructure team to add `/etc/utm/age.key` to
the backup exclusion list of the agent that snapshots this VM. This
is the single most important step — without it, the encrypted YAML
is no more secure than a plaintext file.

## Routine operations

### Rotate a UCS password

```sh
sops /etc/utm/credentials.sops.yaml   # opens decrypted in $EDITOR
# Change the password, save, exit.
sudo systemctl restart utm-creds.service utm.service
```

### Add a new domain

```sh
sops /etc/utm/credentials.sops.yaml
# Add a new entry under "domains:"
sudo systemctl restart utm-creds.service utm.service
```

### Recover from a lost age key

If `/etc/utm/age.key` is destroyed and not backed up elsewhere
(intended), the only path forward is:

1. Generate a new age key on the VM.
2. Re-encrypt `credentials.sops.yaml` with the new public key on
   a workstation that still has access to the old key (e.g., via
   another team member's copy).
3. If no one has the old key: re-create `credentials.sops.yaml`
   from scratch with current credentials, encrypt with the new key,
   commit.

This is the trade-off for keeping the key out of backups.

## Verification

```sh
# Confirm /run/utm/creds.env exists and is mode 600 owned by telegraf
sudo stat /run/utm/creds.env

# Confirm the file is on tmpfs (not on disk)
mount | grep '/run '

# Confirm utm.service started after utm-creds.service
sudo systemctl list-dependencies utm.service
```
