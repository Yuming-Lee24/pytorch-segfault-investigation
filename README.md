# PyTorch Segfault Investigation

Investigation of an intermittent segmentation fault during PyTorch training on an
RTX 4090 / Ubuntu 22.04 workstation.

## Contents

| File | Purpose |
|---|---|
| [DEBUG_REPORT.md](DEBUG_REPORT.md) | Full investigation report — methodology, evidence, conclusions |
| [torture.py](torture.py) | Reproducer: ResNet-152 + AMP training loop that triggers the segfault |
| [logs/gpu_burn/](logs/gpu_burn/) | 8-hour `gpu-burn` stress-test logs |
| [logs/memtester/](logs/memtester/) | 32 GB × 2-pass `memtester` log |
| [logs/torture/](logs/torture/) | Reproducer runs, including successful segfaults |

## Current status

**Leading hypothesis:** hardware fault (RAM / CPU cache / memory overclock instability).
Earlier NVIDIA-driver-regression theory was ruled out by `pip` and `localedef`
segfaults that have no GPU involvement. See [DEBUG_REPORT.md](DEBUG_REPORT.md) §4.4.

**Next step:** run MemTest86+ from USB for ≥ 4–8 hours before doing anything else.

## How to reproduce (once hardware is cleared)

```bash
# 1. Install PyTorch (matching your driver's CUDA version)
pip3 install torch torchvision --index-url https://download.pytorch.org/whl/cu124

# 2. Run the reproducer
cd ~/test
ulimit -c unlimited
export TORCH_SHOW_CPP_STACKTRACES=1 PYTHONFAULTHANDLER=1
python3 -X faulthandler torture.py 2>&1 | tee logs/torture/torture_$(date +%Y%m%d_%H%M%S).log
```

Expected crash within a few minutes while the fault is present. Clean 8-hour run
once the underlying fault is fixed.
