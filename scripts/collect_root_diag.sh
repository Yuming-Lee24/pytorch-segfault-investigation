#!/usr/bin/env bash
# Collect the hardware-error evidence that only root can read.
#   sudo scripts/collect_root_diag.sh
# Read-only: it changes no system setting. The one side effect is that
# reading /dev/mcelog drains the kernel's machine-check buffer, so the
# records end up in the output directory instead.
set -u

if [ "$(id -u)" -ne 0 ]; then
    echo "This script reads root-only files. Run it as: sudo $0" >&2
    exit 1
fi

cd "$(dirname "$0")/.."
OUT=logs/rootdiag/$(date +%Y%m%d_%H%M%S)
mkdir -p "$OUT"

run() {
    local name=$1
    shift
    "$@" > "$OUT/$name" 2>&1 || echo "[exit $?]" >> "$OUT/$name"
}

# Firmware error record left by the previous boot (overwritten at next boot).
cp /sys/firmware/acpi/tables/BERT "$OUT/BERT.table.bin" 2> "$OUT/BERT.err"
cp /sys/firmware/acpi/tables/data/BERT "$OUT/BERT.data.bin" 2>> "$OUT/BERT.err"

# Machine-check records the kernel is still holding.
cat /dev/mcelog > "$OUT/mcelog.bin" 2> "$OUT/mcelog.err"

# Which boot this capture belongs to, and whether it logged a machine check.
{
    echo "boot_id=$(cat /proc/sys/kernel/random/boot_id)"
    echo "booted=$(uptime -s)"
    echo "mcelog_bytes=$(stat -c %s "$OUT/mcelog.bin")"
    journalctl -k -b 0 --no-pager -o short-iso | grep -E 'mce:|BERT|Hardware Error|microcode:'
} > "$OUT/boot_context.txt" 2>&1

# Kernel oops text that pstore carried across the reset.
if [ -d /var/lib/systemd/pstore ]; then
    cp -r /var/lib/systemd/pstore "$OUT/pstore"
fi
run pstore_ls.txt ls -laR /sys/fs/pstore

run dmesg.txt dmesg
run dmidecode.txt dmidecode
run intel_pmt_ls.txt ls -laR /sys/class/intel_pmt
run cpupower_frequency.txt cpupower frequency-info
run cpupower_idle.txt cpupower idle-info

# Model-specific registers, read-only. Some do not exist on every CPU, so a
# failed read is recorded as "-" rather than treated as an error.
if [ -e /dev/cpu/0/msr ]; then
    NCPU=$(nproc --all)
    MSRS="0x8b:microcode 0xce:platform_info 0xe2:cst_config 0x179:mcg_cap
          0x17a:mcg_status 0x198:perf_status 0x199:perf_ctl 0x19c:therm_status
          0x1a0:misc_enable 0x1a2:temp_target 0x1ad:turbo_ratio_limit
          0x1ae:turbo_ratio_limit_cores 0x1b1:pkg_therm_status 0x1fc:power_ctl
          0x606:rapl_units 0x610:pkg_power_limit 0x64f:core_perf_limit_reasons
          0x770:hwp_enable 0x771:hwp_capabilities 0x774:hwp_request"
    {
        printf 'msr\tname'
        for c in $(seq 0 $((NCPU - 1))); do printf '\tcpu%s' "$c"; done
        printf '\n'
        for entry in $MSRS; do
            printf '%s\t%s' "${entry%%:*}" "${entry##*:}"
            for c in $(seq 0 $((NCPU - 1))); do
                printf '\t%s' "$(rdmsr -p "$c" -0 "${entry%%:*}" 2>/dev/null || echo -)"
            done
            printf '\n'
        done
    } > "$OUT/msr.tsv"

    # Machine-check banks: CTL, STATUS, ADDR, MISC for every bank on every CPU.
    {
        printf 'cpu\tbank\tctl\tstatus\taddr\tmisc\n'
        for c in $(seq 0 $((NCPU - 1))); do
            cap=$(rdmsr -p "$c" -0 0x179 2>/dev/null) || continue
            banks=$((0x$cap & 0xff))
            for b in $(seq 0 $((banks - 1))); do
                base=$((0x400 + 4 * b))
                printf '%s\t%s' "$c" "$b"
                for off in 0 1 2 3; do
                    printf '\t%s' "$(rdmsr -p "$c" -0 $((base + off)) 2>/dev/null || echo -)"
                done
                printf '\n'
            done
        done
    } > "$OUT/mca_banks.tsv"

    # Requested core voltage and ratio, sampled for 10 s while idle.
    {
        printf 'sample'
        for c in $(seq 0 $((NCPU - 1))); do printf '\tcpu%s' "$c"; done
        printf '\n'
        for i in $(seq 1 50); do
            printf '%s' "$i"
            for c in $(seq 0 $((NCPU - 1))); do
                printf '\t%s' "$(rdmsr -p "$c" -0 0x198 2>/dev/null || echo -)"
            done
            printf '\n'
            sleep 0.2
        done
    } > "$OUT/perf_status_samples.tsv"
else
    echo "/dev/cpu/0/msr is missing (msr module not loaded); MSRs skipped" > "$OUT/msr.tsv"
fi

run turbostat.txt turbostat --quiet --interval 5 --num_iterations 2
run turbostat_config.txt turbostat --interval 1 --num_iterations 1

if [ -n "${SUDO_UID:-}" ]; then
    chown -R "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" logs/rootdiag
fi
echo "Wrote $OUT"
ls -la "$OUT"
