"""原生 DDP 教学示例：一进程一卡；CPU/Gloo 仅用于流程自检。"""
import argparse
from contextlib import nullcontext
from datetime import timedelta
import os
from pathlib import Path
import random
import time

import torch
from torch import nn
import torch.distributed as dist
from torch.nn.parallel import DistributedDataParallel as DDP
from torch.utils.data import DataLoader, Dataset, DistributedSampler


class 教学数据集(Dataset):
    """按索引生成确定性样本，不依赖下载；不是存储性能测试。"""
    def __init__(self, size):
        self.size = size

    def __len__(self):
        return self.size

    def __getitem__(self, index):
        generator = torch.Generator().manual_seed(index)
        features = torch.randn(32, generator=generator)
        label = int(features[:4].sum() > 0)
        return features, label


def 整理批次(samples):
    # 多进程加载时，此函数在接到该 batch 索引任务的 worker 中执行。
    features, labels = zip(*samples)
    return torch.stack(features), torch.tensor(labels, dtype=torch.long)


def 初始化工作进程(worker_id):
    # PyTorch 已设置 worker 的 torch seed；为 Python 随机增强初始化种子。
    random.seed(torch.initial_seed() % (2**32))


def 参数():
    parser = argparse.ArgumentParser()
    parser.add_argument('--cpu', action='store_true', help='CPU/Gloo 流程自检')
    parser.add_argument('--amp', choices=['off', 'fp16', 'bf16'], default='off')
    parser.add_argument('--epochs', type=int, default=2)
    parser.add_argument('--samples', type=int, default=1040)
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--accumulation', type=int, default=4)
    parser.add_argument('--workers', type=int, default=2)
    parser.add_argument('--output', default='运行输出')
    args = parser.parse_args()
    if min(args.epochs, args.samples, args.batch_size, args.accumulation) < 1 or args.workers < 0:
        parser.error('轮数、样本数、batch 和累计次数必须为正，workers 不能为负')
    if args.cpu and args.amp != 'off':
        parser.error('CPU 自检仅支持 --amp off')
    return args


def main():
    args = 参数()
    local_rank = int(os.environ['LOCAL_RANK'])
    if args.cpu:
        device, backend = torch.device('cpu'), 'gloo'
        torch.set_num_threads(1)
    else:
        torch.cuda.set_device(local_rank)
        device, backend = torch.device('cuda', local_rank), 'nccl'
        if args.amp == 'bf16' and not torch.cuda.is_bf16_supported():
            raise RuntimeError('当前设备不支持示例所需的 BF16')

    dist.init_process_group(backend=backend, timeout=timedelta(minutes=5))
    try:
        rank, world_size = dist.get_rank(), dist.get_world_size()
        # 测试实际 Tensor collective，而不只检查进程组初始化是否返回。
        probe = torch.ones(1, device=device)
        dist.all_reduce(probe, op=dist.ReduceOp.SUM)
        if probe.item() != world_size:
            raise RuntimeError('AllReduce 验证结果不符合预期')
        if rank == 0:
            print(f'通信验证通过：backend={backend}, world_size={world_size}', flush=True)

        torch.manual_seed(42)
        dataset = 教学数据集(args.samples)
        # 丢弃不能均分到 rank 的尾部，避免补齐重复；与 DataLoader.drop_last 不同。
        sampler = DistributedSampler(dataset, shuffle=True, seed=42, drop_last=True)
        loader_options = {}
        if args.workers:
            loader_options.update(prefetch_factor=2, persistent_workers=True,
                                  multiprocessing_context='spawn')
        loader = DataLoader(dataset, sampler=sampler, batch_size=args.batch_size,
                            drop_last=False, num_workers=args.workers,
                            collate_fn=整理批次, worker_init_fn=初始化工作进程,
                            generator=torch.Generator().manual_seed(2026 + rank),
                            pin_memory=not args.cpu, **loader_options)
        if len(loader) == 0:
            raise ValueError('样本不足以分配给全部 rank')

        network = nn.Sequential(nn.Linear(32, 64), nn.ReLU(), nn.Linear(64, 2)).to(device)
        model = DDP(network, device_ids=None if args.cpu else [local_rank])
        optimizer = torch.optim.AdamW(model.parameters(), lr=1e-3)
        scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=10, gamma=0.9)
        scaler = torch.amp.GradScaler('cuda', enabled=args.amp == 'fp16')
        criterion = nn.CrossEntropyLoss(reduction='mean')
        dtype = torch.float16 if args.amp == 'fp16' else torch.bfloat16

        # 使用公开 optimizer hook，区分 scaler.step 被调用与真正完成参数更新。
        update_state = {'count': 0}
        def 记录更新(optimizer, hook_args, hook_kwargs):
            update_state['count'] += 1
        hook = optimizer.register_step_post_hook(记录更新)
        micro_step = 0
        for epoch in range(args.epochs):
            model.train()
            sampler.set_epoch(epoch)  # 必须在 iter(loader) 前调用。
            iterator = iter(loader)
            for start in range(0, len(loader), args.accumulation):
                window_size = min(args.accumulation, len(loader) - start)
                optimizer.zero_grad(set_to_none=True)
                # 先取得本窗口 batch，以便按实际样本数加权，包括最后一个小 batch。
                # 最多额外持有一个累计窗口的 CPU 数据；生产代码也可由批次计划预知权重。
                batches, get_times = [], []
                for _ in range(window_size):
                    begin = time.perf_counter()
                    batches.append(next(iterator))
                    get_times.append(time.perf_counter() - begin)
                local_count = sum(target.numel() for _, target in batches)
                statistics = torch.zeros(2, device=device, dtype=torch.float64)
                for offset, ((inputs, targets), get_time) in enumerate(zip(batches, get_times)):
                    micro_step += 1
                    count = targets.numel()
                    inputs = inputs.to(device, non_blocking=not args.cpu)
                    targets = targets.to(device, non_blocking=not args.cpu)
                    context = nullcontext() if offset == window_size - 1 else model.no_sync()
                    # no_sync 必须覆盖 forward 与 backward。
                    with context:
                        with torch.autocast(device_type=device.type, dtype=dtype,
                                            enabled=args.amp != 'off'):
                            loss = criterion(model(inputs), targets)
                            weighted_loss = loss * (count / local_count)
                        scaler.scale(weighted_loss).backward()
                    statistics[0] += loss.detach().double() * count
                    statistics[1] += count
                    # 只用于理解取数等待；不强制 CUDA 同步，也不称作 GPU 执行耗时。
                    print(f'rank={rank} epoch={epoch} micro_step={micro_step} '
                          f'data_get_time={get_time:.6f}s', flush=True)

                # 各 rank 样本数相同是本示例 sampler/loader 配置保证的前提。
                # 最后一次 backward 同步的是本窗口全部累计贡献。
                scaler.unscale_(optimizer)
                nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                before = update_state['count']
                scaler.step(optimizer)  # 非有限梯度时可能不执行 optimizer.step。
                scaler.update()
                if update_state['count'] > before:
                    scheduler.step()  # 本例按成功参数更新次数调度，各 rank 均执行。
                optimizer.zero_grad(set_to_none=True)

                # 全部 rank 参与；这是日志统计的额外通信，不是 DDP 梯度同步。
                dist.all_reduce(statistics)
                if rank == 0:
                    mean_loss = (statistics[0] / statistics[1]).item()
                    print(f'update={update_state["count"]} loss={mean_loss:.6f} '
                          f'lr={optimizer.param_groups[0]["lr"]:.6g}', flush=True)

            if rank == 0:
                output = Path(args.output)
                output.mkdir(parents=True, exist_ok=True)
                # 同步更新边界保存；不是精确中途恢复的数据游标/RNG 完整快照。
                torch.save({'model': model.module.state_dict(),
                            'optimizer': optimizer.state_dict(),
                            'scheduler': scheduler.state_dict(),
                            'scaler': scaler.state_dict(), 'epoch': epoch,
                            'update_step': update_state['count'], 'args': vars(args)},
                           output / '训练检查点.pt')
            dist.barrier()  # 保存边界协调，不能用 barrier 修复训练中的通信不匹配。
        hook.remove()
    finally:
        dist.destroy_process_group()


if __name__ == '__main__':
    main()  # spawn 模式下必须有入口保护。
