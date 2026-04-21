import torch
import torch.nn as nn
import time
import sys
import os
import faulthandler
import subprocess
from datetime import datetime
from torch.utils.data import DataLoader, Dataset
from torchvision.models import resnet152

assert torch.cuda.is_available(), "CUDA is not available"
device = torch.device("cuda")

os.makedirs("logs/torture", exist_ok=True)
log_path = f"logs/torture/{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
log_file = open(log_path, "w", buffering=1)

# faulthandler writes the C-level traceback directly to the log fd at crash
# time, bypassing Python I/O — this is the only reliable way to get output
# after a segfault in a native extension (CUDA/cuDNN).
faulthandler.enable(log_file)

class Tee:
    def __init__(self, *streams):
        self.streams = streams
    def write(self, data):
        for s in self.streams:
            s.write(data)
    def flush(self):
        for s in self.streams:
            s.flush()

sys.stdout = Tee(sys.__stdout__, log_file)
print(f"Log: {log_path}")

# torch.backends.cudnn.enabled = False


def gpu_stats():
    """Query temp, power draw, and GPU utilisation via nvidia-smi."""
    try:
        out = subprocess.check_output(
            ["nvidia-smi",
             "--query-gpu=temperature.gpu,power.draw,utilization.gpu",
             "--format=csv,noheader,nounits"],
            text=True, timeout=2,
        ).strip()
        temp, power, util = out.split(", ")
        return f"gpu {util}% {temp}C {float(power):.0f}W"
    except Exception:
        return "gpu stats unavailable"


class RandomData(Dataset):
    def __len__(self):
        return 100000

    def __getitem__(self, i):
        return torch.randn(3, 224, 224), torch.randint(0, 1000, (1,)).item()


model = resnet152(weights=None).to(device)
opt = torch.optim.SGD(model.parameters(), lr=0.01)
loss_fn = nn.CrossEntropyLoss()
scaler = torch.amp.GradScaler("cuda")

loader = DataLoader(RandomData(), batch_size=128, num_workers=8, pin_memory=True)

print(f"Driver: {torch.version.cuda}  |  Device: {torch.cuda.get_device_name(0)}")
print(f"PyTorch: {torch.__version__}  |  cuDNN: {torch.backends.cudnn.version()}  |  cuDNN enabled: {torch.backends.cudnn.enabled}")
print(f"VRAM total: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB")
print(f"Duration: 8 hours", flush=True)

step = 0
t0 = time.time()
DURATION_SECONDS = 3600 * 8  # 8 hours

while time.time() - t0 < DURATION_SECONDS:
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)

        # Flush before the forward+backward so the last line in the log
        # tells us exactly which step was in flight when a segfault occurs.
        print(f">>> step {step + 1}", flush=True)

        with torch.amp.autocast("cuda"):
            loss = loss_fn(model(x), y)
        opt.zero_grad()
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
        step += 1

        if step % 100 == 0:
            alloc_gb = torch.cuda.memory_allocated() / 1e9
            reserved_gb = torch.cuda.memory_reserved() / 1e9
            peak_gb = torch.cuda.max_memory_allocated() / 1e9
            elapsed = time.time() - t0
            print(
                f"step {step} loss {loss.item():.3f} "
                f"alloc {alloc_gb:.1f}GB reserved {reserved_gb:.1f}GB peak {peak_gb:.1f}GB "
                f"{gpu_stats()} elapsed {elapsed:.0f}s",
                flush=True,
            )
