import torch
import torch.nn as nn
import time
from torch.utils.data import DataLoader, Dataset
from torchvision.models import resnet152

assert torch.cuda.is_available(), "CUDA is not available"
device = torch.device("cuda")

# torch.backends.cudnn.enabled = False


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

step = 0
t0 = time.time()
DURATION_SECONDS = 3600 * 8  # 4 hours

while time.time() - t0 < DURATION_SECONDS:
    for x, y in loader:
        x = x.to(device, non_blocking=True)
        y = y.to(device, non_blocking=True)
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
                f"elapsed {elapsed:.0f}s",
                flush=True,
            )
