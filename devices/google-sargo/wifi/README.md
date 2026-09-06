# Sargo WCN3990 management-frame protection

This is a build-time, Sargo-only capability descriptor correction. It does not
patch the kernel, replace executable Wi-Fi firmware, disable PMF, or install a
runtime service. Other PocketFed devices are unchanged.

## Three separate pieces

| Piece | Source | Changed here? |
| --- | --- | --- |
| `ath10k_snoc` / `ath10k_core` kernel driver | PocketFed's ARK/COPR kernel | No |
| `ath10k/WCN3990/hw1.0/firmware-5.bin` descriptor | Fedora `atheros-firmware`, from `linux-firmware` | **One capability bit** |
| `qcom/sdm670/sargo/wlanmdsp.mbn` executable firmware | Android vendor partition, extracted by blob-wrangler | No |

Despite its name, this particular `firmware-5.bin` contains only 60 bytes of
ath10k API5 metadata, with no firmware-image or OTP-image TLV. Fedora ships it
compressed as `firmware-5.bin.xz` (108 bytes in the tested package,
`atheros-firmware-20260810-2.fc46.noarch`). Its features were `wowlan`,
`mgmt-tx-by-ref`, and `non-bmi`. `non-bmi` describes a firmware image loaded
out of band, rather than carried in this container.

The missing feature is `ATH10K_FW_FEATURE_MFP_SUPPORT`, bit 12. Adding it changes
the feature TLV payload from `40 00 0c` to `40 10 0c`: byte offset 33 changes
from `00` to `10`, and every other byte remains identical. The descriptor's
CRC32 changes from `b3d4b790` to `eda01cc5`.

In `ath10k_peer_assoc_h_crypto()`, the existing driver requires both negotiated
PMF (`sta->mfp`) and this feature before setting the WMI peer PMF flag. With
the feature absent, the firmware is not given that per-peer configuration.
The TLV WMI flag is `WMI_TLV_PEER_PMF` (`0x08000000`). This code already exists;
the historical introduction is Linux commit
[`90eceb3b5fb0d`](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/commit/?id=90eceb3b5fb0d0f413f475165314d4578c3a46c4).
The old 10.1 version threshold in that commit is not a version comparison
against the different WCN3990 WLAN.HL firmware family.

## Generation and upstream provenance

The metadata file entered linux-firmware in
[`b142c2e0229b`](https://gitlab.com/kernel-firmware/linux-firmware/-/commit/b142c2e0229bc89b44ac527f4f3c3def063bcbc6)
and was still byte-identical at `2f2bf38a3d030a083d8b2b1fea2aa0e9b29a48bd`.
The earlier
[Chromium submission](https://chromium-review.googlesource.com/c/chromiumos/third_party/linux-firmware/+/1125412)
documents generating this kind of descriptor with Qualcomm's open-source
`ath10k-fwencoder`, without supplying an executable firmware image.

`generate-descriptor.py` serializes the public ath10k metadata fields directly.
The following command using
[`qualcomm/qca-swiss-army-knife`](https://github.com/qualcomm/qca-swiss-army-knife)
at `6df4dae3e2f5e4c2903f3cafd40996fc1b3639ce` produces identical corrected bytes:

```sh
python3 tools/scripts/ath10k/ath10k-fwencoder --create \
    --set-fw-api=5 --set-wmi-op-version=tlv --set-htt-op-version=tlv \
    --features=wowlan,mfp-support,mgmt-tx-by-ref,non-bmi \
    --timestamp=1539237028 --output=firmware-5.bin
```

Omitting `mfp-support` reproduces the existing packaged descriptor. The timestamp
is retained for reproducibility; it is not the version/date of Sargo's running
Android firmware. The local generator and its generated configuration are MIT
licensed; this makes no licensing claim about Qualcomm's executable firmware.

The image build validates the packaged descriptor against the exact baseline
or the same descriptor with MFP already enabled. Any other package change fails
the build for review. It then installs an uncompressed descriptor in the same
directory, which the firmware loader prefers over `.xz`, leaving Fedora's
compressed file unchanged. The generator itself is removed in that build step.
Nothing is written to blob-wrangler's mutable `firmware/updates` directory.

The long-term destination is linux-firmware and then Fedora's `atheros-firmware`.
Upstream currently groups this generated metadata under the Qualcomm firmware
licence and requires vendor participation for submissions. That acknowledgement
and compatibility review must not be inferred from the Sargo test. Remove this
temporary image-generation step once a reviewed upstream descriptor reaches
Fedora. Do not generalize it to other WCN3990 firmware variants without review.

## Hardware evidence (2026-09-06)

Tested on Pixel 3a / SDM670 with kernel
`7.1.2-0.pocketfed.sdm670.6.fc46.aarch64` and unchanged Android firmware
`WLAN.HL.2.2.5-00426-QCAHLSWMTPLZ-1` (QMI version `0x225401aa`). The AP was
OpenWrt 24.10.2 with QCA4019 / ath10k-ct. A USB Archer TXE70UH, using
`rtw89_8852cu` in passive monitor mode, provided over-the-air evidence.

On the same WPA3-SAE / PMF-required AP with the same station identity:

| Descriptor | Result |
| --- | --- |
| Original, including after a WLAN driver reload | Association completes; router sends DHCP OFFERs that never reach the phone; valid-FCS unprotected ADDBA requests appear after key installation |
| MFP enabled | DHCP completes, bidirectional traffic works; protected Action frames and block acknowledgements observed in both directions |
| Original restored after success | Original DHCP failure returns |
| MFP enabled again | 2.4 GHz: 30/30 1400-byte DF pings; ordinary unpinned saved profile: 10/10, plus TLS-verified HTTP 200 |

Changing just the bit reverses the post-association failure. The protected
Action payloads were not decrypted, so their exact categories are not claimed.
The captures do not establish every internal step by which the AP/firmware
loses DHCP traffic. No raw captures, network identities, or credentials are
published here.

Limitations: the first corrected-descriptor trial timed out earlier in SAE
authentication and did not reach the comparison point. On 5 GHz the corrected
descriptor connected, but returned 27/30 large pings at approximately -80 dBm
and suffered a low-ACK disconnection/reconnection. This is not a claim of
general 5 GHz stability, suspend/resume reliability, or certification across
all WCN3990 firmware. Persistent image/cold-boot validation remains to be done;
the hardware tests used a reversible runtime descriptor override.

Offline regression tests run in CI and need no device:

```sh
python3 devices/google-sargo/wifi/test-descriptor.py
```
