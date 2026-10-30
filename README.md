# lunar-python-opt-lab

一句话：上游是纯 Python 的中国农历/公历转换库 `6tail/lunar-python`；本次只改一处——把 `LunarYear.fromYear()` 的“只缓存上一年”单槽缓存换成按年份索引的字典缓存，跨年查询不再整年重算节气与合朔。

Upstream: https://github.com/6tail/lunar-python

## 结果

基准负载：从 2000-01-01 到 2023-12-31 的 24 年窗口内，用固定种子随机抽取 N 个公历日期，逐个调用 `Solar.fromYmd(...).getLunar()` 并读取 `toString/toFullString/年干支/月/日/节气/生肖`。日期跨年乱序，因此单槽缓存几乎每次都要重建 `LunarYear`。

| 规模（日期数） | 基线中位数 | 优化后中位数 | 加速比 |
| --- | --- | --- | --- |
| 80 | 0.366708 s | 0.014526 s | 25.24x |
| 240 | 1.214175 s | 0.043599 s | 27.85x |
| 720 | 3.607842 s | 0.129719 s | 27.81x |

三个规模加速比的中位数：**27.81x**（5 次计时样本的中位数；warmup 3 次不计入）。原始样本在 `benchmark/raw/`，每个规模 5 个文件，共 30 个。

口径说明：warmup 的 3 遍已经把 24 年窗口内的 `LunarYear` 全部放进缓存，因此表中是“重复跨年查询”的稳定态数字；单次冷启动转换不会变快（缓存未命中时仍要构造一次）。该负载对应批量换算跨年份日期的场景。另：字典缓存没有淘汰策略，长期存活进程若访问大量不同年份会持续持有对应 `LunarYear`；本基准的 24 年窗口下峰值 RSS 见 G5。

改动只有 `lunar_python/LunarYear.py` 一个文件：`git diff --stat` 为 6 insertions / 8 deletions（`patch.diff`，1865 字节）。对象构造后不可变（无 setter，`compute()` 只在 `__init__` 调用），因此复用实例不改变任何返回值；线程锁保留。

## 差分测试

`tests/test_diff.py` 用两个独立解释器分别加载未改动的上游与打过补丁的副本，对 1243 组输入（1200 组随机日期 + 43 组边界/极值/节气/闰日/年月边界）渲染同一组字段，按 JSON 行逐字节比较：

```
cases: 1243
baseline  sha256: 83d77498bdcf30797865867f4a0ff08c4295f67df6502797c6c5a51e446a9d8c
optimized sha256: 83d77498bdcf30797865867f4a0ff08c4295f67df6502797c6c5a51e446a9d8c
differences: 0
RESULT: IDENTICAL (byte-for-byte)
```

## 质量闸门 G1–G5

| 闸门 | 结论 | 复现命令 |
| --- | --- | --- |
| G1 上游测试全绿 | 通过：`Ran 241 tests ... OK`，0 failed | `cd /tmp/lunar-opt-lab-opt && python3 -m unittest discover -s test -p "*Test.py"` |
| G2 差分一致 | 通过：1243 组，0 差异，两个 sha256 相同 | `python3 tests/test_diff.py --baseline /tmp/lunar-opt-lab-base --optimized /tmp/lunar-opt-lab-opt` |
| G3 中位加速 ≥1.15x | 通过：27.81x | 见下方基准命令，读取 `benchmark/*.json` 的 `results[].median_s` |
| G4 最大规模不退化 ≥0.95x | 通过：720 日期规模 27.81x | 同上，最大规模 `scale=720` |
| G5 峰值 RSS ≤1.10x | 通过：`/usr/bin/time -v` 16188 KB → 16256 KB，比值 1.004；`benchmark/*.json` 内 `resource.ru_maxrss` 自报 15744 → 15872 KB，比值 1.008 | `/usr/bin/time -v python3 benchmark/bench.py --lib /tmp/lunar-opt-lab-base --impl baseline --out /tmp/g5-base.json --raw-dir /tmp/g5raw`（优化侧同命令换 `--lib /tmp/lunar-opt-lab-opt --impl optimized`） |

所有计时样本的相对标准差最大为 1.21%（优化侧 scale=80），其余均 <1%，未观察到 GC/页错误导致的明显噪声。

## 复现（3 条命令）

```bash
rm -rf /tmp/lunar-opt-lab-base /tmp/lunar-opt-lab-opt && git clone --depth=1 git@github-linluozi:6tail/lunar-python.git /tmp/lunar-opt-lab-base && git clone --depth=1 git@github-linluozi:6tail/lunar-python.git /tmp/lunar-opt-lab-opt && git -C /tmp/lunar-opt-lab-opt apply "$PWD/patch.diff"
python3 tests/test_diff.py --baseline /tmp/lunar-opt-lab-base --optimized /tmp/lunar-opt-lab-opt
python3 benchmark/bench.py --lib /tmp/lunar-opt-lab-base --impl baseline --out /tmp/baseline.json --raw-dir /tmp/raw && python3 benchmark/bench.py --lib /tmp/lunar-opt-lab-opt --impl optimized --out /tmp/optimized.json --raw-dir /tmp/raw
```

`patch.diff` 已在干净上游 clone 上通过 `git apply --check`。

## 环境

- CPU：AMD EPYC 7K62 48-Core Processor（本机 4 核）
- 内存：3812564 KB（约 3.64 GB）
- Python：3.12.3
- 种子：20261030（基准与差分测试共用）
- 计时器：`time.perf_counter()`；每个规模 warmup 3 次 + 5 次计时
- 上游 commit：`009870fbab8784901662e8d36571056d0a271f78`（depth=1 clone）
